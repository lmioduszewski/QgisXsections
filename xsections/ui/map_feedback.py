"""What the section looks like on the map: line, tolerance swath, plotted explorations and other points (seeps,
springs ...), sheet breaks, and the distance hovered on the preview.

Everything is drawn with canvas items (rubber bands and small text items), never written to a layer, so nothing
of it reaches a layout or an export. Geometries arrive in the section CRS; the rubber bands transform them to the
canvas CRS. The hover cursor (show_cursor) moves on every mouse move, so it transforms its few points itself with
a transform built once per model and canvas CRS.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsCsException, QgsGeometry,
                       QgsPointXY, QgsProject)
from qgis.gui import QgsMapCanvas, QgsMapCanvasItem, QgsRubberBand
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen

from ..core.hover import distance_text

LINE_COLOR = QColor(214, 39, 40)
SWATH_FILL = QColor(214, 39, 40, 38)
SWATH_STROKE = QColor(214, 39, 40, 110)
POINT_COLOR = QColor(255, 127, 14)
MATCH_COLOR = QColor(128, 0, 0)
CURSOR_COLOR = QColor("#14313d")         # the hover cursor (navy, as the preview's guide tags)
CONNECTOR_COLOR = QColor(20, 49, 61, 204)
HALO = QColor(255, 255, 255, 235)


class MapLabel(QgsMapCanvasItem):
    """A short bold text with a white halo, anchored to a map point (in canvas CRS)."""

    def __init__(self, canvas: QgsMapCanvas, text: str, point: QgsPointXY, color: QColor = MATCH_COLOR,
                 size_pt: float = 9.0, dx: float = 6.0, dy: float = -6.0):
        super().__init__(canvas)
        self.text = text
        self.point = point
        self.color = QColor(color)
        self.font = QFont()
        self.font.setPointSizeF(size_pt)
        self.font.setBold(True)
        self.dx, self.dy = dx, dy
        fm = QFontMetricsF(self.font)
        self._w, self._h = fm.horizontalAdvance(text) + 6.0, fm.height() + 6.0
        self.setZValue(1000)
        self.updatePosition()

    def boundingRect(self) -> QRectF:
        return QRectF(self.dx - 3.0, self.dy - self._h, self._w + 6.0, self._h + 6.0)

    def updatePosition(self) -> None:
        self.setPos(self.toCanvasCoordinates(self.point))

    def paint(self, painter: QPainter, option=None, widget=None) -> None:
        path = QPainterPath()
        path.addText(QPointF(self.dx, self.dy), self.font, self.text)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(255, 255, 255, 230), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color)
        painter.drawPath(path)


class CursorMarker(MapLabel):
    """The distance hovered on the preview, on the map: a navy dot with a white halo and a white centre on the
    section line, and the distance beside it, on the side of the line that `toward` (a second point, canvas CRS)
    lies on. The text sits clear of the dot whatever the line's direction on screen.

    Unlike MapLabel it moves and changes its text on every mouse move, so it calls prepareGeometryChange() before
    its bounding rectangle changes (else the canvas keeps stale paint)."""

    DOT_R = 6.5          # px, the dot's radius (to the middle of its halo)
    HALO_W = 2.4         # px, the white ring around the dot
    CENTRE_R = 1.8       # px, the white centre
    CLEAR = 12.0         # px from the dot's centre to the nearest edge of the text
    TEXT_HALO = 3.2      # px, the white halo around the text

    toward: Optional[QgsPointXY] = None
    _off = QPointF(0.0, -CLEAR)     # text centre from the dot, px (class defaults: MapLabel.__init__ positions us)
    _tw = _th = _ascent = 0.0

    def __init__(self, canvas: QgsMapCanvas):
        super().__init__(canvas, "", QgsPointXY(0.0, 0.0), color=CURSOR_COLOR, size_pt=9.0)
        self.font.setWeight(QFont.Weight.DemiBold)
        self.setZValue(1001)                       # above the other labels
        self.setVisible(False)

    def set_cursor(self, point: QgsPointXY, toward: Optional[QgsPointXY], text: str) -> None:
        """Move the dot to `point` with `text` on the side of `toward` (both canvas CRS)."""
        self.prepareGeometryChange()
        self.point, self.toward = QgsPointXY(point), (QgsPointXY(toward) if toward is not None else None)
        if text != self.text or not self._th:
            self.text = text
            fm = QFontMetricsF(self.font)
            self._tw, self._ascent = fm.horizontalAdvance(text), fm.ascent()
            self._th = fm.ascent() + fm.descent()
        self.updatePosition()
        self.update()

    def _label_offset(self, pos: QPointF) -> QPointF:
        """Where the text's centre goes from the dot (px): toward `toward` on screen, far enough that the text's
        box stays CLEAR px from the dot's centre."""
        vx, vy = 0.0, -1.0                         # (up, when there is no side to go by)
        if self.toward is not None:
            q = self.toCanvasCoordinates(self.toward)
            dx, dy = q.x() - pos.x(), q.y() - pos.y()
            n = math.hypot(dx, dy)
            if n > 1e-12 and math.isfinite(n):
                vx, vy = dx / n, dy / n
        d = self.CLEAR + abs(vx) * self._tw / 2.0 + abs(vy) * self._th / 2.0
        return QPointF(vx * d, vy * d)

    def text_rect(self) -> QRectF:
        """The text's box, item coordinates (the dot's centre at 0, 0)."""
        return QRectF(self._off.x() - self._tw / 2.0, self._off.y() - self._th / 2.0, self._tw, self._th)

    def boundingRect(self) -> QRectF:
        r = self.DOT_R + self.HALO_W / 2.0 + 1.0
        rect = QRectF(-r, -r, 2.0 * r, 2.0 * r)
        if self.text:
            m = self.TEXT_HALO / 2.0 + 1.5
            rect = rect.united(self.text_rect().adjusted(-m, -m, m, m))
        return rect

    def updatePosition(self) -> None:
        pos = self.toCanvasCoordinates(self.point)
        off = self._label_offset(pos)              # (a turned or reprojected canvas turns the line on screen)
        if abs(off.x() - self._off.x()) > 1e-6 or abs(off.y() - self._off.y()) > 1e-6:
            self.prepareGeometryChange()
            self._off = off
        self.setPos(pos)

    def paint(self, painter: QPainter, option=None, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(255, 255, 255), self.HALO_W))
        painter.setBrush(self.color)
        painter.drawEllipse(QPointF(0.0, 0.0), self.DOT_R, self.DOT_R)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(QPointF(0.0, 0.0), self.CENTRE_R, self.CENTRE_R)
        if not self.text:
            return
        rect = self.text_rect()
        path = QPainterPath()
        path.addText(QPointF(rect.left(), rect.top() + self._ascent), self.font, self.text)
        painter.setPen(QPen(HALO, self.TEXT_HALO, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color)
        painter.drawPath(path)


def match_ticks(line: QgsGeometry, stations_ft: Sequence[float], dist_factor: float,
                half_len: float) -> List[Tuple[float, List[QgsPointXY]]]:
    """Short lines across `line` at each station (ft), `half_len` each side, in the line's CRS units.

    Returns (station, [p1, p2]) pairs; stations off the line are skipped.
    """
    out = []
    for st in stations_ft:
        d = st / dist_factor
        p = line.interpolate(d)
        if p.isEmpty():
            continue
        a = line.interpolateAngle(d)          # radians clockwise from north
        c = p.asPoint()
        nx, ny = math.cos(a), -math.sin(a)    # perpendicular to the line direction (sin a, cos a)
        out.append((st, [QgsPointXY(c.x() - nx * half_len, c.y() - ny * half_len),
                         QgsPointXY(c.x() + nx * half_len, c.y() + ny * half_len)]))
    return out


def match_stations(plan) -> List[float]:
    """Stations (ft) of the match lines between tiled sheets."""
    if plan is None or len(getattr(plan, "pages", []) or []) < 2:
        return []
    out = []
    for page in plan.pages:
        if page.match_right is not None:
            out.append(float(page.match_right))
    return sorted(set(out))


class MapFeedback:
    """Owns every canvas item the plugin draws. `remove()` takes them all off the canvas."""

    CURSOR_RING = 26            # px, the ring around the point pointed at (outside the orange one, 18 px)

    def __init__(self, canvas: QgsMapCanvas):
        self.canvas = canvas
        self.swath = QgsRubberBand(canvas, Qgis.GeometryType.Polygon)
        self.swath.setFillColor(SWATH_FILL)
        self.swath.setStrokeColor(SWATH_STROKE)
        self.swath.setWidth(1)
        self.line = QgsRubberBand(canvas, Qgis.GeometryType.Line)
        self.line.setColor(LINE_COLOR)
        self.line.setWidth(3)
        self.ticks = QgsRubberBand(canvas, Qgis.GeometryType.Line)
        self.ticks.setColor(MATCH_COLOR)
        self.ticks.setWidth(2)
        self.ticks.setLineStyle(Qt.PenStyle.DashLine)
        self.points = QgsRubberBand(canvas, Qgis.GeometryType.Point)
        self.points.setIcon(QgsRubberBand.IconType.ICON_CIRCLE)     # a ring around the layer's own symbol
        self.points.setIconSize(18)
        self.points.setStrokeColor(POINT_COLOR)
        self.points.setFillColor(QColor(0, 0, 0, 0))
        self.points.setWidth(3)
        self.labels: List[MapLabel] = []
        # the hover cursor (show_cursor): the dot and its distance, the ring around the point pointed at (an
        # exploration or an other point), the dashed line from it to its foot on the section line, the dotted line
        # from the map cursor
        self.projection = QgsRubberBand(canvas, Qgis.GeometryType.Line)
        self.projection.setColor(CURSOR_COLOR)
        self.projection.setWidth(2)
        self.projection.setLineStyle(Qt.PenStyle.DashLine)
        self.connector = QgsRubberBand(canvas, Qgis.GeometryType.Line)
        self.connector.setColor(CONNECTOR_COLOR)
        self.connector.setWidth(1)
        self.connector.setLineStyle(Qt.PenStyle.DotLine)
        self.ring = QgsRubberBand(canvas, Qgis.GeometryType.Point)
        self.ring.setIcon(QgsRubberBand.IconType.ICON_CIRCLE)
        self.ring.setIconSize(self.CURSOR_RING)
        self.ring.setStrokeColor(CURSOR_COLOR)
        self.ring.setFillColor(QColor(0, 0, 0, 0))
        self.ring.setWidth(3)
        for band in (self.projection, self.connector, self.ring):
            band.setZValue(999)                    # over the section's own bands, under the labels
        self.cursor: Optional[CursorMarker] = CursorMarker(canvas)
        self._visible = True
        self._last: Optional[Tuple] = None     # what to redraw when the canvas CRS changes
        self._section: Optional[Tuple] = None  # (line, crs, ft per unit, length ft, settings) of the shown model
        self._to_canvas_ct: Optional[QgsCoordinateTransform] = None    # section CRS -> canvas CRS (None: same)
        self._cursor: Optional[Tuple] = None   # (station, hit, map_point) of the cursor shown, or None
        self._cursor_hit = None                # the hit the ring and the projection are drawn for
        canvas.destinationCrsChanged.connect(self._reproject)

    # ---- public
    def show_line(self, geom: Optional[QgsGeometry], crs: QgsCoordinateReferenceSystem,
                  start_label: str = "", end_label: str = "", tolerance_units: float = 0.0) -> None:
        """Only the line (and swath) before a section model exists, e.g. while the DEM is missing."""
        self.clear()
        if geom is None or geom.isEmpty():
            return
        self._last = ("line", geom, crs, start_label, end_label, tolerance_units)
        self._draw_line(geom, crs, start_label, end_label, tolerance_units)

    def show_model(self, model, settings, plan=None) -> None:
        """Line, swath, the plotted points (model.hits, the explorations left off by him not among them, and
        model.other_points: one ring each, in the one `points` band) and sheet breaks from a built SectionModel."""
        self.clear()
        crs = QgsCoordinateReferenceSystem.fromWkt(model.section_crs_wkt) if model.section_crs_wkt \
            else self.canvas.mapSettings().destinationCrs()
        line = QgsGeometry.fromWkt(model.line_wkt) if model.line_wkt else QgsGeometry()
        if line.isEmpty():
            return
        self._last = ("model", model, settings, plan)
        f = model.dist_factor or 1.0
        self._section = (line, crs, f, float(model.length), settings)
        self._to_canvas_ct = self._make_transform(crs)
        # no swath without an exploration layer or other points on: nothing is projected onto a ground-only section
        projected = getattr(model, "has_points", getattr(model, "has_explorations", True))
        tol_units = settings.tolerance_ft / f if projected else 0.0
        self._draw_line(line, crs, settings.start_label, settings.end_label, tol_units)
        points = list(model.hits or []) + list(getattr(model, "other_points", None) or [])
        if points:
            pts = QgsGeometry.fromMultiPointXY([QgsPointXY(p.x, p.y) for p in points])
            self.points.setToGeometry(pts, crs)
        stations = match_stations(plan)
        if stations:
            ticks = match_ticks(line, stations, f, max(tol_units * 1.4, 40.0 / f))
            if ticks:
                self.ticks.setToGeometry(QgsGeometry.fromMultiPolylineXY([t[1] for t in ticks]), crs)
            for st, (_, p2) in ticks:
                self._add_label(f"MATCH {_station_text(st)}", p2, crs, size_pt=8.0)
        self.set_visible(self._visible)

    def show_cursor(self, station: float, hit=None, map_point: Optional[QgsPointXY] = None) -> None:
        """The distance hovered on the preview: a dot on the section line `station` ft from its start (following
        the bends) with the distance beside it. With `hit` (the point pointed at: an exploration or an other point,
        anything with x, y, station and side) a ring around it and a dashed line to its foot on the section line;
        with `map_point` (the map cursor, section CRS) a thin dotted line from it to the dot. The distance goes on
        the side of the line away from the point, or from the map cursor. Hidden past either end of the line, and
        while there is no section model."""
        if self.cursor is None or self._section is None or station is None or not math.isfinite(station):
            self.hide_cursor()
            return
        line, _crs, f, length, settings = self._section
        slack = 1e-9 * max(length, 1.0)            # (the model length and the line's differ in the last digits)
        if station < -slack or station > length + slack:
            self.hide_cursor()
            return
        d = min(max(station / f, 0.0), line.length())
        foot = line.interpolate(d)
        if foot.isEmpty():
            self.hide_cursor()
            return
        foot = foot.asPoint()
        # the side of the line the distance goes on: away from the point or the map cursor, else the left
        left = True
        if hit is not None:
            left = hit.side != "L"
        elif map_point is not None:
            left = line.closestSegmentWithContext(QgsPointXY(map_point))[3] > 0     # (> 0: the point is right)
        a = line.interpolateAngle(d)               # radians clockwise from north
        nx, ny = (-math.cos(a), math.sin(a)) if left else (math.cos(a), -math.sin(a))
        eps = 1.0 / f                              # 1 ft along the normal: that side on screen, whatever the CRS
        p = self._to_canvas(foot)
        q = self._to_canvas(QgsPointXY(foot.x() + nx * eps, foot.y() + ny * eps))
        if p is None or q is None:
            self.hide_cursor()
            return
        self.cursor.set_cursor(p, q, distance_text(station, settings))
        self._cursor = (float(station), hit, QgsPointXY(map_point) if map_point is not None else None)
        self._set_hit(hit)
        target = self._to_canvas(QgsPointXY(map_point)) if map_point is not None else None
        if target is not None:
            self.connector.setToGeometry(QgsGeometry.fromPolylineXY([target, p]))
        elif self.connector.numberOfVertices():
            self.connector.reset(Qgis.GeometryType.Line)
        for item in self._cursor_items():
            item.setVisible(self._visible)

    def hide_cursor(self) -> None:
        """Take the hover cursor (dot, ring, projection, connector) off the map until the next show_cursor."""
        self._cursor = None
        self._cursor_hit = None
        if self.cursor is not None:
            self.cursor.setVisible(False)
        for band, kind in self._cursor_bands():
            if band.numberOfVertices():
                band.reset(kind)

    def cursor_shown(self) -> bool:
        """True while show_cursor's dot is on the map (also while the feedback is hidden)."""
        return self._cursor is not None

    def _cursor_bands(self) -> List[Tuple[QgsRubberBand, Qgis.GeometryType]]:
        G = Qgis.GeometryType
        return [(b, k) for b, k in ((self.projection, G.Line), (self.connector, G.Line), (self.ring, G.Point))
                if b is not None]

    def _typed_bands(self) -> List[Tuple[QgsRubberBand, Qgis.GeometryType]]:
        G = Qgis.GeometryType
        own = [(b, k) for b, k in ((self.swath, G.Polygon), (self.line, G.Line), (self.ticks, G.Line),
                                   (self.points, G.Point)) if b is not None]
        return own + self._cursor_bands()

    def _cursor_items(self) -> list:
        return [b for b, _ in self._cursor_bands()] + ([self.cursor] if self.cursor is not None else [])

    def _bands(self) -> list:
        return [b for b, _ in self._typed_bands()]

    def clear(self) -> None:
        self._last = None
        self._section = None
        self._to_canvas_ct = None
        self.hide_cursor()
        for band, kind in self._typed_bands():
            band.reset(kind)
        self._remove_labels()

    def set_visible(self, visible: bool) -> None:
        self._visible = visible
        for item in self._bands() + self.labels:
            item.setVisible(visible)
        if self.cursor is not None:
            self.cursor.setVisible(visible and self._cursor is not None)

    def remove(self) -> None:
        """Take every item off the canvas (plugin unload)."""
        try:
            self.canvas.destinationCrsChanged.disconnect(self._reproject)
        except (TypeError, RuntimeError):
            pass
        self.clear()
        scene = self.canvas.scene()
        for item in self._bands() + ([self.cursor] if self.cursor is not None else []):
            if scene is not None:
                scene.removeItem(item)
        self.swath = self.line = self.ticks = self.points = None
        self.projection = self.connector = self.ring = None
        self.cursor = None

    def item_count(self) -> int:
        """Rubber bands and labels (the hover cursor's too) still on the canvas scene (for tests)."""
        scene = self.canvas.scene()
        ours = self._bands() + self.labels + ([self.cursor] if self.cursor is not None else [])
        return sum(1 for item in ours if scene is not None and item.scene() is scene)

    # ---- internals
    def _make_transform(self, crs: QgsCoordinateReferenceSystem) -> Optional[QgsCoordinateTransform]:
        """Section CRS -> canvas CRS, built once per model and canvas CRS (None when they are the same)."""
        dest = self.canvas.mapSettings().destinationCrs()
        if crs.isValid() and dest.isValid() and crs != dest:
            return QgsCoordinateTransform(crs, dest, QgsProject.instance())
        return None

    def _to_canvas(self, point: QgsPointXY) -> Optional[QgsPointXY]:
        """A section CRS point in the canvas CRS (None when it does not transform)."""
        if self._to_canvas_ct is None:
            return QgsPointXY(point)
        try:
            return self._to_canvas_ct.transform(point)
        except QgsCsException:
            return None

    def _set_hit(self, hit) -> None:
        """The ring and the projection of the point pointed at (redrawn only when it changes)."""
        if hit is self._cursor_hit:
            return
        self._cursor_hit = None
        for band, kind in ((self.ring, Qgis.GeometryType.Point), (self.projection, Qgis.GeometryType.Line)):
            if band.numberOfVertices():
                band.reset(kind)
        if hit is None or self._section is None:
            return
        line, _crs, f, _length, _settings = self._section
        at = self._to_canvas(QgsPointXY(hit.x, hit.y))
        if at is None:
            return
        self.ring.setToGeometry(QgsGeometry.fromPointXY(at))
        foot = line.interpolate(min(max(hit.station / f, 0.0), line.length()))
        foot = self._to_canvas(foot.asPoint()) if not foot.isEmpty() else None
        if foot is not None:
            self.projection.setToGeometry(QgsGeometry.fromPolylineXY([at, foot]))
        self._cursor_hit = hit

    def _draw_line(self, geom, crs, start_label, end_label, tol_units) -> None:
        self.line.setToGeometry(geom, crs)
        if tol_units > 0:
            swath = geom.buffer(tol_units, 8, Qgis.EndCapStyle.Flat, Qgis.JoinStyle.Round, 2)
            if not swath.isEmpty():
                self.swath.setToGeometry(swath, crs)
        verts = [QgsPointXY(v) for v in geom.vertices()]
        if len(verts) >= 2:
            if start_label:
                self._add_label(start_label, verts[0], crs, color=LINE_COLOR, size_pt=10.0)
            if end_label:
                self._add_label(end_label, verts[-1], crs, color=LINE_COLOR, size_pt=10.0)

    def _add_label(self, text: str, point: QgsPointXY, crs: QgsCoordinateReferenceSystem,
                   color: QColor = MATCH_COLOR, size_pt: float = 9.0) -> None:
        dest = self.canvas.mapSettings().destinationCrs()
        if crs.isValid() and dest.isValid() and crs != dest:
            try:
                point = QgsCoordinateTransform(crs, dest, QgsProject.instance()).transform(point)
            except Exception:   # QgsCsException: leave the label out
                return
        item = MapLabel(self.canvas, text, point, color=color, size_pt=size_pt)
        item.setVisible(self._visible)
        self.labels.append(item)

    def _remove_labels(self) -> None:
        scene = self.canvas.scene()
        for item in self.labels:
            if scene is not None:
                scene.removeItem(item)
        self.labels = []

    def _reproject(self, *args) -> None:
        last, cursor = self._last, self._cursor
        if last is None:
            return
        if last[0] == "line":
            self.show_line(*last[1:])
        else:
            self.show_model(*last[1:])           # (a new section -> canvas transform too)
            if cursor is not None:                 # the hover cursor stays where it was
                self.show_cursor(*cursor)


def _station_text(st: float) -> str:
    n = int(round(st))
    return f"{n // 100}+{n % 100:02d}"
