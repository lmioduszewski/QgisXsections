"""XSections plugin shell: toolbar/menu action, the two docks, project wiring, clean unload."""
from __future__ import annotations

import os
import traceback
from typing import Optional

from qgis.core import Qgis, QgsMessageLog, QgsProject
from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QAction, QIcon

# Import the sub-packages by name, so QGIS's plugin import hook records them and unloadPlugin /
# reloadPlugin (and installing an update over a running copy) removes them from sys.modules too.
from . import core, render, ui  # noqa: F401

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
MENU = "&XSections"


class XSectionsPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action: Optional[QAction] = None
        self.dock = None                  # ui.dock.XSectionsDock (right)
        self.preview_dock: Optional[QgsDockWidget] = None   # bottom, holds ui.preview.PreviewWidget
        self.preview = None
        self._project_signals = []

    # ---------------------------------------------------------------- QGIS hooks
    def initGui(self) -> None:
        from .ui.dock import XSectionsDock
        from .ui.preview import PreviewWidget

        mw = self.iface.mainWindow()
        self.action = QAction(QIcon(os.path.join(PLUGIN_DIR, "icon.svg")), "XSections", mw)
        self.action.setObjectName("mActionXSections")
        self.action.setCheckable(True)
        self.action.setToolTip("XSections: cross sections from a DEM and explorations, exported at exact scale")
        self.action.toggled.connect(self.set_panels_visible)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu(MENU, self.action)

        self.preview_dock = QgsDockWidget("XSections preview", mw)
        self.preview_dock.setObjectName("XSectionsPreviewDock")
        self.preview = PreviewWidget(self.preview_dock)
        self.preview_dock.setWidget(self.preview)

        self.dock = XSectionsDock(self.iface, self.preview, mw)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.iface.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.preview_dock)
        self.dock.hide()
        self.preview_dock.hide()
        self.dock.visibilityChanged.connect(self._sync_action)

        prj = QgsProject.instance()
        for signal, slot in ((prj.readProject, self._on_project_read), (prj.cleared, self._on_project_cleared),
                             (prj.crsChanged, self._on_project_crs_changed)):
            signal.connect(slot)
            self._project_signals.append((signal, slot))
        self._restore()

    def unload(self) -> None:
        for signal, slot in self._project_signals:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._project_signals = []
        if self.preview is not None:
            self.preview.leave_full_screen()     # (full screen: its dock back in its place before it goes)
        if self.dock is not None:
            self.dock.cleanup()
            try:
                self.dock.visibilityChanged.disconnect(self._sync_action)
            except (TypeError, RuntimeError):
                pass
            self.iface.removeDockWidget(self.dock)
            self.dock.setParent(None)
            self.dock.deleteLater()
            self.dock = None
        if self.preview_dock is not None:
            self.iface.removeDockWidget(self.preview_dock)
            self.preview_dock.setParent(None)
            self.preview_dock.deleteLater()
            self.preview_dock = None
            self.preview = None
        if self.action is not None:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu(MENU, self.action)
            self.action.deleteLater()
            self.action = None

    # ---------------------------------------------------------------- behaviour
    def set_panels_visible(self, visible: bool) -> None:
        """Toolbar button: open or close both panels."""
        for dock in (self.dock, self.preview_dock):
            if dock is None:
                continue
            dock.setVisible(visible)
            if visible:
                dock.raise_()
        if self.dock is not None:
            self.dock.feedback.set_visible(visible)

    def _sync_action(self, visible: bool) -> None:
        if self.action is None or self.dock is None:
            return
        self.action.blockSignals(True)
        self.action.setChecked(not self.dock.isHidden())
        self.action.blockSignals(False)

    def _restore(self) -> None:
        """Settings from the project; a project the panel cannot read falls back to the defaults, so
        one bad entry never leaves the plugin half started."""
        if self.dock is None:
            return
        try:
            self.dock.restore_from_project()
        except Exception:
            QgsMessageLog.logMessage("Could not restore the XSections settings saved in this project; using "
                                     "the defaults.\n" + traceback.format_exc(), "XSections",
                                     Qgis.MessageLevel.Warning)
            from .core.model import Settings
            self.dock.apply_settings(Settings())

    def _on_project_read(self, *args) -> None:
        self._restore()

    def _on_project_cleared(self) -> None:
        if self.preview is not None:
            self.preview.leave_full_screen()     # (nothing to show full screen: the preview back in its dock)
        if self.dock is not None:
            self.dock.project_cleared()

    def _on_project_crs_changed(self) -> None:
        """The section CRS can depend on the project CRS (geographic DEM): rebuild."""
        if self.dock is not None:
            self.dock._schedule()
