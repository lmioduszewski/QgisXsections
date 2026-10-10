"""Icons of the Other features symbols (0.3.6): the pictures of the symbol drop-down, painted with Qt from the same
geometry the sheets draw (render/symbols.py: glyph, glyph_bbox), and a polygon row's bracket mark.

Theme-independent: only the given colours (the symbol's, white insides and edges, an optional background), never the
palette, so an icon looks the same in a light and a dark QGIS. One nominal size for every symbol (ICON_S_RATIO of the
height, as in the approved mockup), so they compare as they do on paper; a symbol is shrunk only when it would not
fit. A resting symbol stands 2 px above the bottom edge, as on the ground line; the benchmark is centred.
"""
from __future__ import annotations

from typing import Optional, Tuple

from qgis.PyQt.QtCore import QPointF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QIcon, QPainter, QPen, QPixmap, QPolygonF

from ..render.symbols import Dot, Fill, Letter, Ring, Stroke, glyph, glyph_bbox, symbol, tint, usual_color

ICON_W, ICON_H = 22, 16          # the mockup's 22 x 16 icon (logical px)
ICON_S_RATIO = 11.0 / 16.0       # the nominal size: 11 px in a 16 px icon (the mockup's S)
ICON_MARGIN = 1.0                # px kept clear on every side (2 below a resting symbol)
_REST_PX = 2.0                   # a resting symbol's lowest ink this far above the bottom edge
BRACKET_LW, BRACKET_TICK = 1.5, 4.0   # the bracket mark: line width, tick length (px)
BRACKET_DASH = (4.0, 2.0)        # ... dashed: px (divided by the width: Qt's dashes are in pen widths)


def _pixmap(width: int, height: int, dpr: float, background: Optional[str]) -> QPixmap:
    pm = QPixmap(max(1, int(round(width * dpr))), max(1, int(round(height * dpr))))
    pm.setDevicePixelRatio(dpr)
    pm.fill(QColor(background) if background else QColor(Qt.GlobalColor.transparent))
    return pm


def _pen(color: str, width: float, cap: Qt.PenCapStyle = Qt.PenCapStyle.RoundCap) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(cap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def icon_place(key: str, width: float = ICON_W, height: float = ICON_H) -> Tuple[float, float, float, float]:
    """(size_pt, f, ox, oy) of `key`'s icon: the glyph's nominal size (1 px = 1 pt), the scale that fits its ink in
    the box (at most 1), and where its origin goes (logical px, y down: a glyph point (x, y) is drawn at
    (ox + f x, oy - f y))."""
    size_pt = height * ICON_S_RATIO
    left, right, bottom, top = (v * 72.0 for v in glyph_bbox(key, size_pt, 1.0))
    bw, bh = max(right - left, 1e-9), max(top - bottom, 1e-9)
    f = min(1.0, (width - 2.0 * ICON_MARGIN) / bw, (height - ICON_MARGIN - _REST_PX) / bh)
    ox = width / 2.0 - f * (left + right) / 2.0
    if symbol(key).rests:
        oy = height - _REST_PX + f * bottom
    else:                                  # the benchmark: centred
        oy = height / 2.0 + f * (bottom + top) / 2.0
    return size_pt, f, ox, oy


def paint_symbol(p: QPainter, key: str, color: str, width: float = ICON_W, height: float = ICON_H) -> None:
    """Paint `key`'s symbol in `color` into the box (0, 0, width, height) of `p` (logical px)."""
    size_pt, f, ox, oy = icon_place(key, width, height)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    p.translate(ox, oy)
    p.scale(f, f)                          # strokes shrink too

    def pt(x: float, y: float) -> QPointF:
        return QPointF(x * 72.0, -y * 72.0)
    for g in glyph(key, size_pt, 1.0):
        if isinstance(g, Stroke):
            p.setPen(_pen(color, g.w * 72.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(QPolygonF([pt(x, y) for x, y in zip(g.xs, g.ys)]))
        elif isinstance(g, Ring):          # white inside
            p.setPen(_pen(color, g.w * 72.0))
            p.setBrush(QColor("white"))
            p.drawEllipse(pt(g.cx, g.cy), g.r * 72.0, g.r * 72.0)
        elif isinstance(g, Dot):
            p.setPen(_pen("white", g.edge * 72.0) if g.edge > 0 else QPen(Qt.PenStyle.NoPen))
            p.setBrush(QColor(color))
            p.drawEllipse(pt(g.cx, g.cy), g.r * 72.0, g.r * 72.0)
        elif isinstance(g, Fill):
            face = color if g.face == "color" else "white" if g.face == "white" else tint(QColor(color).name())
            p.setPen(_pen("white" if g.edge == "white" else color, g.w * 72.0))
            p.setBrush(QColor(face))
            p.drawPolygon(QPolygonF([pt(x, y) for x, y in g.pts]))
        elif isinstance(g, Letter):        # the application's font at the letter's size, on its baseline
            font = QFont(QGuiApplication.font())
            font.setPixelSize(max(1, int(round(g.size_pt))))
            p.setFont(font)
            p.setPen(QPen(QColor(color)))
            adv = QFontMetricsF(font).horizontalAdvance(g.text)
            base = pt(g.x, g.y)
            p.drawText(QPointF(base.x() - adv if g.ha == "right" else base.x(), base.y()), g.text)
    p.restore()


def symbol_pixmap(key: str, color: Optional[str] = None, width: int = ICON_W, height: int = ICON_H,
                  dpr: float = 1.0, background: Optional[str] = None) -> QPixmap:
    """`key`'s symbol in `color` (None: its usual colour) on a width x height (logical px) pixmap at device pixel
    ratio `dpr`, transparent unless `background` (a colour name) is given. An unknown key: the fallback circle."""
    pm = _pixmap(width, height, dpr, background)
    p = QPainter(pm)
    paint_symbol(p, key, color or usual_color(key), width, height)
    p.end()
    return pm


def symbol_icon(key: str, color: Optional[str] = None, width: int = ICON_W, height: int = ICON_H,
                background: Optional[str] = None) -> QIcon:
    """`key`'s symbol as an icon with its pixmaps at device pixel ratios 1 and 2 (symbol_pixmap)."""
    icon = QIcon()
    for dpr in (1.0, 2.0):
        icon.addPixmap(symbol_pixmap(key, color, width, height, dpr, background))
    return icon


def bracket_pixmap(color: str, style: str = "solid", width: int = ICON_W, height: int = ICON_H, dpr: float = 1.0,
                   background: Optional[str] = None) -> QPixmap:
    """A polygon row's mark (the legend's bracket swatch scaled into the box): a line across at 2/3 of the height
    from x = 3 to width - 3, ticks BRACKET_TICK px down at both ends, BRACKET_LW px wide, solid or dashed
    ("dash": the line BRACKET_DASH px, its ticks solid, as on the sheet)."""
    pm = _pixmap(width, height, dpr, background)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(color), BRACKET_LW)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)
    y = float(round(height / 3.0))
    x0, x1 = 3.0, width - 3.0
    if style != "dash":
        p.drawPolyline(QPolygonF([QPointF(x0, y + BRACKET_TICK), QPointF(x0, y), QPointF(x1, y),
                                  QPointF(x1, y + BRACKET_TICK)]))
    else:                                  # the ticks solid from half the line's width above it (they cover the
        top = y - BRACKET_LW / 2.0         # corners), then the line dashed between them
        p.drawLine(QPointF(x0, top), QPointF(x0, y + BRACKET_TICK))
        p.drawLine(QPointF(x1, top), QPointF(x1, y + BRACKET_TICK))
        pen.setDashPattern([v / BRACKET_LW for v in BRACKET_DASH])
        p.setPen(pen)
        p.drawLine(QPointF(x0, y), QPointF(x1, y))
    p.end()
    return pm


def bracket_icon(color: str, style: str = "solid", width: int = ICON_W, height: int = ICON_H,
                 background: Optional[str] = None) -> QIcon:
    """A polygon row's mark as an icon with its pixmaps at device pixel ratios 1 and 2 (bracket_pixmap)."""
    icon = QIcon()
    for dpr in (1.0, 2.0):
        icon.addPixmap(bracket_pixmap(color, style, width, height, dpr, background))
    return icon
