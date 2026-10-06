"""What the section looks like on the map: line, tolerance swath, plotted explorations, sheet breaks.

Everything is drawn with canvas items (rubber bands and small text items), never written to a layer.
Geometries arrive in the section CRS; the rubber bands transform them to the canvas CRS.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsGeometry, QgsPointXY)
from qgis.gui import QgsMapCanvas, QgsMapCanvasItem, QgsRubberBand
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen

LINE_COLOR = QColor(214, 39, 40)
SWATH_FILL = QColor(214, 39, 40, 38)
SWATH_STROKE = QColor(214, 39, 40, 110)
POINT_COLOR = QColor(255, 127, 14)
MATCH_COLOR = QColor(128, 0, 0)


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
        self._visible = True
        self._last: Optional[Tuple] = None     # what to redraw when the canvas CRS changes
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
        """Line, swath, plotted explorations and sheet breaks from a built SectionModel."""
        self.clear()
        crs = QgsCoordinateReferenceSystem.fromWkt(model.section_crs_wkt) if model.section_crs_wkt \
            else self.canvas.mapSettings().destinationCrs()
        line = QgsGeometry.fromWkt(model.line_wkt) if model.line_wkt else QgsGeometry()
        if line.isEmpty():
            return
        self._last = ("model", model, settings, plan)
        f = model.dist_factor or 1.0
        # no swath without an explorations layer: nothing is projected onto a ground-only section
        tol_units = settings.tolerance_ft / f if getattr(model, "has_explorations", True) else 0.0
        self._draw_line(line, crs, settings.start_label, settings.end_label, tol_units)
        if model.hits:
            pts = QgsGeometry.fromMultiPointXY([QgsPointXY(h.x, h.y) for h in model.hits])
            self.points.setToGeometry(pts, crs)
        stations = match_stations(plan)
        if stations:
            ticks = match_ticks(line, stations, f, max(tol_units * 1.4, 40.0 / f))
            if ticks:
                self.ticks.setToGeometry(QgsGeometry.fromMultiPolylineXY([t[1] for t in ticks]), crs)
            for st, (_, p2) in ticks:
                self._add_label(f"MATCH {_station_text(st)}", p2, crs, size_pt=8.0)
        self.set_visible(self._visible)

    def _bands(self) -> list:
        return [b for b in (self.swath, self.line, self.ticks, self.points) if b is not None]

    def clear(self) -> None:
        self._last = None
        for band in self._bands():
            if band is self.swath:
                band.reset(Qgis.GeometryType.Polygon)
            elif band is self.points:
                band.reset(Qgis.GeometryType.Point)
            else:
                band.reset(Qgis.GeometryType.Line)
        self._remove_labels()

    def set_visible(self, visible: bool) -> None:
        self._visible = visible
        for item in self._bands() + self.labels:
            item.setVisible(visible)

    def remove(self) -> None:
        """Take every item off the canvas (plugin unload)."""
        try:
            self.canvas.destinationCrsChanged.disconnect(self._reproject)
        except (TypeError, RuntimeError):
            pass
        self.clear()
        scene = self.canvas.scene()
        for band in self._bands():
            if scene is not None:
                scene.removeItem(band)
        self.swath = self.line = self.ticks = self.points = None

    def item_count(self) -> int:
        """Rubber bands + labels still on the canvas scene (for tests)."""
        scene = self.canvas.scene()
        ours = self._bands() + self.labels
        return sum(1 for item in ours if scene is not None and item.scene() is scene)

    # ---- internals
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
            from qgis.core import QgsCoordinateTransform, QgsProject
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
        last = self._last
        if last is None:
            return
        if last[0] == "line":
            self.show_line(*last[1:])
        else:
            self.show_model(*last[1:])


def _station_text(st: float) -> str:
    n = int(round(st))
    return f"{n // 100}+{n % 100:02d}"
