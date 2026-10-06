"""XSections: geologic cross sections at exact scale (QGIS 4 plugin)."""
import importlib

# Imported by the plugin at start-up; pypdf is optional and imported only when a PDF is written.
REQUIRED = ("numpy", "matplotlib", "matplotlib.backends.backend_qtagg")

HOW_TO_FIX = (
    "XSections needs numpy and matplotlib (with its Qt backend), and QGIS's Python could not import: "
    "{missing}. On Windows with the OSGeo4W installer, run the installer again (Advanced Install) and "
    "add the python3-matplotlib package. Otherwise, on Windows open the OSGeo4W Shell (Start menu, QGIS "
    "folder) and run: python -m pip install matplotlib; on Linux install your distribution's "
    "python3-matplotlib package. Then restart QGIS."
)


def missing_dependencies():
    """[(module, error)] for each REQUIRED module that does not import."""
    missing = []
    for name in REQUIRED:
        try:
            importlib.import_module(name)
        except Exception as e:           # ImportError, or a broken install failing in other ways
            missing.append((name, f"{type(e).__name__}: {e}"))
    return missing


def classFactory(iface):  # noqa: N802 - QGIS entry point name
    missing = missing_dependencies()
    if missing:
        return MissingDependencies(iface, missing)
    from .plugin import XSectionsPlugin
    return XSectionsPlugin(iface)


class MissingDependencies:
    """Stands in for the plugin when a dependency is missing: one error in the message bar, nothing else."""

    def __init__(self, iface, missing):
        self.iface = iface
        self.missing = missing
        self.item = None

    def initGui(self):  # noqa: N802 - QGIS API
        from qgis.core import Qgis, QgsMessageLog
        from qgis.gui import QgsMessageBarItem
        text = HOW_TO_FIX.format(missing=", ".join(name for name, _ in self.missing))
        QgsMessageLog.logMessage(text + "\n" + "\n".join(err for _, err in self.missing), "XSections",
                                 Qgis.MessageLevel.Critical)
        self.item = QgsMessageBarItem("XSections", text, Qgis.MessageLevel.Critical, 0)
        self.iface.messageBar().pushItem(self.item)

    def unload(self):
        if self.item is not None:
            try:
                self.iface.messageBar().popWidget(self.item)
            except RuntimeError:         # the user already closed the message
                pass
            self.item = None
