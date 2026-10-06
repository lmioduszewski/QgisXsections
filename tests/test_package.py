"""scripts/package.py: the zip for Install from ZIP, read back the way QGIS reads it.

QGIS's installer (pyplugin_installer) takes the first name in the zip ending in metadata.txt, uses
its folder as the plugin id, and parses metadata.txt with installer_data.getInstalledPlugin.
"""
import importlib.util
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.fixtures import ROOT, start_app

start_app()

from pyplugin_installer import installer_data  # noqa: E402
from pyplugin_installer.version_compare import isCompatible, pyQgisVersion  # noqa: E402
from qgis import utils as qgis_utils  # noqa: E402


def load_package_script():
    spec = importlib.util.spec_from_file_location("xsec_package", os.path.join(ROOT, "scripts", "package.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P = load_package_script()


class PluginZip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="xsec_package_")
        cls.zip = P.build(Path(cls.tmp, "dist"))
        with zipfile.ZipFile(cls.zip) as zf:
            cls.names = zf.namelist()
            cls.plugins_dir = os.path.join(cls.tmp, "plugins")      # stands in for the profile's plugins folder
            zf.extractall(cls.plugins_dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_license_ships(self):
        """The repo's GPL-2.0 LICENSE goes in the plugin folder, where plugins.qgis.org looks for it."""
        self.assertIn("xsections/LICENSE", self.names)
        with zipfile.ZipFile(self.zip) as zf:
            text = zf.read("xsections/LICENSE").decode("ascii")
        self.assertEqual(text, Path(ROOT, "LICENSE").read_text(encoding="ascii"))
        self.assertIn("GNU GENERAL PUBLIC LICENSE", text)
        self.assertIn("Version 2, June 1991", text)
        self.assertNotIn("QGIS", text)          # the plain licence, without QGIS's own Qt exception

    def test_name_and_contents(self):
        version = P.read_version()
        self.assertEqual(self.zip.name, f"xsections-{version}.zip")
        self.assertEqual(P.check(self.zip), [])
        self.assertEqual({n.split("/")[0] for n in self.names}, {"xsections"})
        self.assertFalse([n for n in self.names if "__pycache__" in n or n.endswith((".pyc", ".pyo"))])
        self.assertFalse([n for n in self.names if "/tests/" in n])
        shipped = sorted(n for n in self.names if n.endswith(".py"))
        source = sorted("xsections/" + p.relative_to(Path(ROOT, "xsections")).as_posix()
                        for p in Path(ROOT, "xsections").rglob("*.py") if "__pycache__" not in p.parts)
        self.assertEqual(shipped, source)
        for extra in ("xsections/metadata.txt", "xsections/icon.svg", "xsections/render/_pdf_incremental.py"):
            self.assertIn(extra, self.names)

    def test_qgis_finds_the_plugin_id(self):
        """installer.installFromZipFile: first sorted name ending in metadata.txt; its folder is the id."""
        first = sorted(n for n in self.names if n.endswith("metadata.txt"))[0]
        self.assertEqual(os.path.split(first)[0], "xsections")

    def test_installer_reads_metadata(self):
        path = os.path.join(self.plugins_dir, "xsections")
        info = installer_data.Plugins().getInstalledPlugin("xsections", path, False)
        self.assertEqual(info["error"], "", info["error_details"])
        self.assertEqual(info["name"], "XSections")
        self.assertEqual(info["version_installed"], P.read_version())
        self.assertTrue(info["experimental"])
        self.assertTrue(os.path.isfile(info["icon"]))
        self.assertIn("0.1.0", info["changelog"])
        self.assertEqual(info["code_repository"], "")               # placeholder URLs are gone
        self.assertEqual(info["tracker"], "")
        tags = [t.strip() for t in info["tags"].split(",")]
        for tag in ("geology", "hydrogeology", "cross section", "profile", "lidar", "boreholes", "wells"):
            self.assertIn(tag, tags)

    def test_compatible_with_4_2_1(self):
        found = dict(qgis_utils.findPlugins(self.plugins_dir))
        self.assertEqual(list(found), ["xsections"])
        cp = found["xsections"]
        self.assertIsNotNone(cp, "qgis.utils could not parse metadata.txt")
        lo, hi = cp.get("general", "qgisMinimumVersion"), cp.get("general", "qgisMaximumVersion")
        self.assertTrue(isCompatible("4.2.1", lo, hi))
        self.assertTrue(isCompatible(pyQgisVersion(), lo, hi))
        self.assertFalse(isCompatible("3.44.0", lo, hi))
        self.assertFalse(isCompatible("4.1.3", lo, hi))   # minimum is 4.2, the version it is tested on
        self.assertEqual(lo, "4.2")
        self.assertEqual(cp.get("general", "hasProcessingProvider"), "no")

    def test_check_finds_problems(self):
        bad = Path(self.tmp, "bad.zip")
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("xsections/metadata.txt", "[general]\n")
            zf.writestr("xsections/__pycache__/plugin.cpython-312.pyc", b"")
            zf.writestr("xsections/tests/test_x.py", "")
            zf.writestr("xsections/core/x.py", 'P = r"D:\\Users\\someone\\AppData\\Local\\Temp\\scratchpad"\n')
            zf.writestr("xsections/ui/y.py", 'Q = "/home/someone/data"  # https://example.org/users/x\n')
            zf.writestr("extra/metadata.txt", "")
        problems = "\n".join(P.check(bad))
        for expected in ("missing xsections/__init__.py", "exactly one metadata.txt", "extra/metadata.txt: not a",
                         "plugin.cpython-312.pyc: bytecode", "test_x.py: not needed at runtime",
                         "x.py, line 1: contains an absolute Windows path", "'AppData'", "'scratchpad'",
                         "y.py, line 1: contains a user folder"):
            self.assertIn(expected, problems)
        self.assertNotIn("users/x", problems)                       # a URL is not a user folder


if __name__ == "__main__":
    unittest.main()
