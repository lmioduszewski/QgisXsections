"""Map tools for the section line: draw one on the map, or pick a feature from a line layer."""
from __future__ import annotations

from typing import List, Optional

from qgis.core import Qgis, QgsGeometry, QgsVectorLayer
from qgis.gui import (QgsAdvancedDigitizingDockWidget, QgsIdentifyMenu, QgsMapCanvas, QgsMapMouseEvent,
                      QgsMapTool, QgsMapToolCapture, QgsMapToolIdentify)
from qgis.PyQt.QtCore import QPoint, Qt, pyqtSignal
from qgis.PyQt.QtGui import QKeyEvent


class DrawSectionTool(QgsMapToolCapture):
    """Python port of QGIS's QgsMapToolProfileCurve.

    Left-click to add vertices (snapping and the Advanced Digitizing panel work), right-click to finish.
    Emits `curveCaptured(QgsGeometry)` in the canvas CRS. Esc cancels and emits `canceled`.
    """

    curveCaptured = pyqtSignal(QgsGeometry)
    canceled = pyqtSignal()

    def __init__(self, canvas: QgsMapCanvas, cad_dock: Optional[QgsAdvancedDigitizingDockWidget]):
        super().__init__(canvas, cad_dock, QgsMapToolCapture.CaptureMode.CaptureLine)
        self.setToolName("XSections: draw section line")

    # always work in map CRS, whatever the active layer is
    def layer(self):  # noqa: D401 - Qt override
        return None

    def capabilities(self):
        return QgsMapToolCapture.Capability.SupportsCurves

    def supportsTechnique(self, technique) -> bool:
        return technique != Qgis.CaptureTechnique.Shape

    def lineCaptured(self, line) -> None:
        geom = QgsGeometry(line.clone())
        if geom.isEmpty() or geom.constGet().nCoordinates() < 2:
            return
        self.curveCaptured.emit(geom)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        super().keyPressEvent(e)
        if e.key() == Qt.Key.Key_Escape:
            self.canceled.emit()


class PickLineTool(QgsMapTool):
    """Click a line feature on the map. Emits `featurePicked(layer, fid)`.

    Several candidates under the cursor open QGIS's identify menu to choose one.
    """

    featurePicked = pyqtSignal(object, object)     # QgsVectorLayer, feature id (int)
    nothingFound = pyqtSignal()
    canceled = pyqtSignal()

    def __init__(self, canvas: QgsMapCanvas):
        super().__init__(canvas)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def flags(self):
        return QgsMapTool.Flag.AllowZoomRect

    def canvasReleaseEvent(self, e: QgsMapMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        results = QgsIdentifyMenu.findFeaturesOnCanvas(e, self.canvas(), [Qgis.GeometryType.Line])
        results = [r for r in results if isinstance(r.mLayer, QgsVectorLayer) and r.mFeature.hasGeometry()]
        if not results:
            self.nothingFound.emit()
            return
        chosen = self.choose(results, e.pos())
        if chosen is not None:
            self.featurePicked.emit(chosen.mLayer, chosen.mFeature.id())

    def choose(self, results: List[QgsMapToolIdentify.IdentifyResult], pos: QPoint):
        """One result: take it. Several: let the user choose from the identify menu."""
        if len(results) == 1:
            return results[0]
        menu = QgsIdentifyMenu(self.canvas())
        menu.setAllowMultipleReturn(False)
        menu.setExecWithSingleResult(False)
        global_pos = self.canvas().mapToGlobal(QPoint(pos.x() + 5, pos.y() + 5))
        selected = menu.exec(results, global_pos)
        menu.deleteLater()
        return selected[0] if selected else None

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            e.accept()
            self.canceled.emit()
        else:
            e.ignore()
