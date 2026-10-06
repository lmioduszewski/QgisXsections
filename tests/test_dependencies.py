"""Missing dependencies: QGIS gets a stand-in plugin that says how to fix it; pypdf stays optional.

Missing modules are simulated with None in sys.modules (then importing them raises ImportError).
"""
import ast
import os
import sys
import unittest
from unittest import mock

from tests.fixtures import ROOT, start_app

APP = start_app()

from qgis.core import Qgis  # noqa: E402
from qgis.gui import QgsMessageBar  # noqa: E402
from qgis.PyQt.QtCore import QCoreApplication, QEvent  # noqa: E402

import xsections  # noqa: E402
from xsections.plugin import XSectionsPlugin  # noqa: E402


def fake_iface():
    iface = mock.MagicMock()
    bar = QgsMessageBar()
    iface.messageBar.return_value = bar
    return iface, bar


class MissingMatplotlib(unittest.TestCase):
    def test_stub_plugin(self):
        iface, bar = fake_iface()
        with mock.patch.dict(sys.modules, {"matplotlib": None}):
            plugin = xsections.classFactory(iface)
        self.assertIsInstance(plugin, xsections.MissingDependencies)
        self.assertEqual([name for name, _ in plugin.missing], ["matplotlib"])

        plugin.initGui()
        items = bar.items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].level(), Qgis.MessageLevel.Critical)
        self.assertEqual(items[0].title(), "XSections")
        for part in ("could not import: matplotlib.", "OSGeo4W", "python3-matplotlib", "pip install matplotlib",
                     "restart QGIS"):
            self.assertIn(part, items[0].text())
        for call in (iface.addToolBarIcon, iface.addPluginToMenu, iface.addDockWidget):
            call.assert_not_called()

        plugin.unload()
        self.assertEqual(bar.items(), [])
        plugin.unload()                                   # a second unload is harmless

    def test_unload_after_the_user_closed_the_message(self):
        iface, bar = fake_iface()
        plugin = xsections.MissingDependencies(iface, [("numpy", "ModuleNotFoundError: numpy")])
        plugin.initGui()
        bar.popWidget(plugin.item)                        # the user clicks the close button
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        plugin.unload()
        self.assertEqual(bar.items(), [])

    def test_every_required_module_is_checked(self):
        blocked = {name: None for name in xsections.REQUIRED}
        with mock.patch.dict(sys.modules, blocked):
            missing = [name for name, _ in xsections.missing_dependencies()]
        self.assertEqual(missing, ["numpy", "matplotlib", "matplotlib.backends.backend_qtagg"])

    def test_real_plugin_when_all_present(self):
        self.assertEqual(xsections.missing_dependencies(), [])
        self.assertIsInstance(xsections.classFactory(mock.MagicMock()), XSectionsPlugin)


def import_time_modules(tree):
    """Modules imported by statements that run when the module is imported (not inside functions)."""
    found, todo = [], list(tree.body)
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append(node.module or "")
        todo.extend(ast.iter_child_nodes(node))
    return found


class PypdfIsOptional(unittest.TestCase):
    def test_no_module_imports_pypdf_at_import_time(self):
        plugin_dir = os.path.join(ROOT, "xsections")
        checked = 0
        for folder, _, files in os.walk(plugin_dir):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), path)
                bad = [m for m in import_time_modules(tree) if m.split(".")[0] == "pypdf"]
                self.assertEqual(bad, [], os.path.relpath(path, ROOT))
                checked += 1
        self.assertGreater(checked, 15)


if __name__ == "__main__":
    unittest.main()
