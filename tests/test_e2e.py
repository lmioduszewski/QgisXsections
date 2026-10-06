"""End to end: the plugin as QGIS loads it, driven through the dock's public API.

classFactory -> initGui -> open the panels -> choose layers -> refresh -> readouts, preview and map
feedback -> Export… (PDF and PNG) -> measure the files from their pixels -> unload leaves nothing behind.

The iface is qgis.testing's mock, wrapped around a real QMainWindow so the docks are really docked.
The real-data case runs only when XSECTIONS_REALDATA points at the folder with CDF_wells.shp and
cdf_lidar.tif; those files are copied to a temp folder first so nothing is ever written next to them.
"""
import math
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from tests.fixtures import REALDATA, STANDARD_LAYOUT, default_settings, load_project, start_app

APP = start_app()

import numpy as np  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from qgis.core import (Qgis, QgsApplication, QgsCoordinateTransform, QgsGeometry, QgsPointXY,  # noqa: E402
                       QgsProject, QgsRasterLayer, QgsVectorLayer)
from qgis.gui import (QgsAdvancedDigitizingDockWidget, QgsDockWidget, QgsMapToolPan, QgsMessageBar,  # noqa: E402
                      QgsRubberBand)
from qgis.PyQt import sip  # noqa: E402
from qgis.PyQt.QtCore import QCoreApplication, QElapsedTimer, QEvent, Qt  # noqa: E402
from qgis.PyQt.QtWidgets import QVBoxLayout, QWidget  # noqa: E402

from tests import measure as M  # noqa: E402
from xsections import classFactory  # noqa: E402
from xsections.render.pdfprefs import read_print_prefs  # noqa: E402
from xsections.ui.map_feedback import MapLabel  # noqa: E402
from xsections.ui.preview import SHEET_GID, main_axes  # noqa: E402

DPI = 300
PX_TOL = 0.5          # px per inch, both axes
REAL_FILES = ["CDF_wells.cpg", "CDF_wells.dbf", "CDF_wells.prj", "CDF_wells.shp", "CDF_wells.shx",
              "cdf_lidar.tif"]


# ------------------------------------------------------------------ a QGIS-like main window
def make_qgis_window(width=1500, height=950):
    """qgis.testing's mocked iface around a real main window: map canvas in the middle, a message bar
    above it, and addDockWidget/removeDockWidget that really dock. Returns (iface, main_window)."""
    import qgis.testing as qt
    qt.QGISAPP = QgsApplication.instance()          # get_iface() must not start a second application
    from qgis.testing.mocked import get_iface
    iface = get_iface()
    mw = iface.mainWindow()
    canvas = iface.mapCanvas()
    central = QWidget(mw)
    lay = QVBoxLayout(central)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    bar = QgsMessageBar(central)
    lay.addWidget(bar)
    lay.addWidget(canvas, 1)
    mw.setCentralWidget(central)
    iface.messageBar.return_value = bar
    cad = QgsAdvancedDigitizingDockWidget(canvas, mw)
    mw.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, cad)
    cad.hide()                                      # QGIS keeps its CAD dock closed until asked
    iface.cadDockWidget.return_value = cad
    iface.activeLayer.return_value = None
    iface.addDockWidget.side_effect = mw.addDockWidget
    iface.removeDockWidget.side_effect = mw.removeDockWidget
    mw.resize(width, height)
    mw.show()
    APP.processEvents()
    return iface, mw


def show_layers(canvas, layers, crs, extent=None, timeout_ms=20000):
    """Put `layers` on the canvas and wait for the map to finish rendering."""
    canvas.setDestinationCrs(crs)
    canvas.setLayers(layers)
    if extent is not None:
        canvas.setExtent(extent)
    canvas.refresh()
    wait_for_canvas(canvas, timeout_ms)


def wait_for_canvas(canvas, timeout_ms=20000):
    t = QElapsedTimer()
    t.start()
    for _ in range(5):                       # refresh() is scheduled on a timer: let it start
        APP.processEvents()
    while canvas.isDrawing() and t.elapsed() < timeout_ms:
        APP.processEvents()
    APP.processEvents()


def flush_deletes():
    """Run deleteLater() now (there is no event loop in tests)."""
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    APP.processEvents()


def our_canvas_items(canvas):
    return [i for i in canvas.scene().items() if isinstance(i, (QgsRubberBand, MapLabel))]


def export_via_dock(dock, path, filter_text):
    """Press Export… with the file dialog answered by `path`."""
    with mock.patch("xsections.ui.dock.QFileDialog.getSaveFileName", return_value=(path, filter_text)):
        return dock.export_section()


def line_through_points(points_layer, crs, project, margin=300.0):
    """A straight line along the main axis of the points (in `crs`), `margin` past the outermost ones.
    Returns (geometry, tolerance that catches every point)."""
    ct = QgsCoordinateTransform(points_layer.crs(), crs, project)
    xy = []
    for f in points_layer.getFeatures():
        p = ct.transform(f.geometry().asPoint())
        xy.append((p.x(), p.y()))
    P = np.array(xy)
    c = P.mean(axis=0)
    axis = np.linalg.svd(P - c)[2][0]
    if axis[1] < 0:                          # read south to north
        axis = -axis
    along = (P - c) @ axis
    perp = (P - c) @ np.array([-axis[1], axis[0]])
    a = c + axis * (along.min() - margin)
    b = c + axis * (along.max() + margin)
    geom = QgsGeometry.fromPolylineXY([QgsPointXY(*a), QgsPointXY(*b)])
    return geom, float(math.ceil(np.abs(perp).max() + 10.0))


def folder_state(folder):
    return sorted((e.name, e.stat().st_size, e.stat().st_mtime_ns) for e in os.scandir(folder))


def copy_realdata(dest):
    for name in REAL_FILES:
        shutil.copy2(os.path.join(REALDATA, name), os.path.join(dest, name))
    return os.path.join(dest, "cdf_lidar.tif"), os.path.join(dest, "CDF_wells.shp")


# ------------------------------------------------------------------ shared checks
class E2ECase(unittest.TestCase):
    def open_plugin(self):
        self.iface, self.mw = make_qgis_window()
        self.canvas = self.iface.mapCanvas()
        self.items_before = len(our_canvas_items(self.canvas))
        self.plugin = classFactory(self.iface)
        self.plugin.initGui()
        self.addCleanup(self._unload_if_loaded)
        self.plugin.action.trigger()                     # the toolbar button opens both panels
        APP.processEvents()
        self.dock = self.plugin.dock
        self.assertTrue(self.dock.isVisible())
        self.assertTrue(self.plugin.preview_dock.isVisible())
        self.assertTrue(self.plugin.action.isChecked())

    def _unload_if_loaded(self):
        if getattr(self, "plugin", None) is not None and self.plugin.dock is not None:
            self.plugin.unload()
        if getattr(self, "mw", None) is not None:
            self.mw.close()
            self.mw.deleteLater()
            flush_deletes()

    def check_preview(self, n_hits):
        pv = self.plugin.preview
        APP.processEvents()
        pv.render_pending()
        self.assertTrue(pv.has_section())
        self.assertEqual(pv.last_error, "")
        self.assertTrue(pv.figure.axes)
        ax = main_axes(pv.figure, self.dock.plan)
        x0, x1 = ax.get_xlim()
        self.assertAlmostEqual(x0, 0.0)
        self.assertAlmostEqual(x1, self.dock.plan.plot_length)
        self.assertEqual(tuple(ax.get_ylim()), (self.dock.plan.z_min, self.dock.plan.z_max))
        self.assertIn(f"{n_hits} exploration", pv.status.text())
        return pv

    def check_raster(self, rgb, page, grid, label):
        """Frame = plot size in inches x 300 (+/- 1 px); 300 +/- 0.5 px per inch on both axes."""
        m = M.measure(rgb, DPI, 0.1, 0.1, grid)
        for ax, inches in (("x", page.plot_w), ("y", page.plot_h)):
            d = m[ax]
            self.assertAlmostEqual(d["frame_px"], inches * DPI, delta=1.0, msg=f"{label} {ax} frame")
            self.assertAlmostEqual(d["px_per_in"], DPI, delta=PX_TOL, msg=f"{label} {ax} px per inch")
            self.assertGreaterEqual(d["n_major"], 1, msg=f"{label} {ax} majors")
            for sp in M.normalised_major_spacings(d["major_spacing_px"], DPI):
                self.assertAlmostEqual(sp, DPI, delta=PX_TOL, msg=f"{label} {ax} major spacing")
        return m

    def check_png(self, path, page, grid):
        rgb, info = M.load_png(path)
        self.assertEqual(info["size"], (round(page.page_w * DPI), round(page.page_h * DPI)))
        self.assertAlmostEqual(info["pHYs"]["dpi_x"], DPI, delta=0.01)
        self.assertAlmostEqual(info["pHYs"]["dpi_y"], DPI, delta=0.01)
        return self.check_raster(rgb, page, grid, os.path.basename(path))

    def check_pdf(self, path, pages, grid, measure_pages=(1,)):
        rd = PdfReader(path)
        self.assertEqual(len(rd.pages), len(pages))
        for pg, layout in zip(rd.pages, pages):
            self.assertEqual([float(v) for v in pg.mediabox], [0.0, 0.0, layout.page_w * 72, layout.page_h * 72])
        self.assertEqual(read_print_prefs(path).get("/PrintScaling"), "/None")
        for n in measure_pages:                      # rasterised independently by GDAL's PDF driver
            rgb, _ = M.load_pdf_raster(path, DPI, page=n)
            self.check_raster(rgb, pages[n - 1], grid, f"{os.path.basename(path)} page {n}")
        return rd

    def check_unload(self):
        plugin, iface, canvas, mw = self.plugin, self.iface, self.canvas, self.mw
        action, dock, pdock = plugin.action, plugin.dock, plugin.preview_dock
        bands = list(dock.feedback._bands())
        self.assertGreater(len(our_canvas_items(canvas)), self.items_before)
        pan = QgsMapToolPan(canvas)
        canvas.setMapTool(pan)
        dock.btn_draw.setChecked(True)                   # leave a map tool of ours active
        self.assertIs(canvas.mapTool(), dock._draw_tool)

        plugin.unload()
        flush_deletes()
        iface.removeToolBarIcon.assert_called_once_with(action)
        iface.removePluginMenu.assert_called_once_with("&XSections", action)
        self.assertEqual(iface.removeDockWidget.call_count, 2)
        self.assertIsNone(plugin.action)
        self.assertIsNone(plugin.dock)
        self.assertIsNone(plugin.preview_dock)
        self.assertTrue(sip.isdeleted(action))
        self.assertTrue(sip.isdeleted(dock))
        self.assertTrue(sip.isdeleted(pdock))
        names = [d.objectName() for d in mw.findChildren(QgsDockWidget)]
        self.assertNotIn("XSectionsDock", names)
        self.assertNotIn("XSectionsPreviewDock", names)
        self.assertEqual(len(our_canvas_items(canvas)), self.items_before)
        for band in bands:
            self.assertIsNone(band.scene())
        self.assertIs(canvas.mapTool(), pan)             # the previous map tool is back
        self.assertEqual(plugin._project_signals, [])
        QgsProject.instance().cleared.emit()             # nothing of ours is connected any more


# ------------------------------------------------------------------ synthetic project
class SyntheticEndToEnd(E2ECase):
    def setUp(self):
        self.prj, self.dem, self.pts, self.lines = load_project(kind="terrain")
        self.out = tempfile.mkdtemp(prefix="xsec_e2e_")
        self.addCleanup(shutil.rmtree, self.out, True)

    def test_full_flow(self):
        self.open_plugin()
        d = self.dock
        self.assertIs(d.dem_layer.currentLayer(), self.dem)        # guessed from the layer names
        self.assertIs(d.points_layer.currentLayer(), self.pts)
        self.assertTrue(d.compact_layout.isChecked())               # the default layout (0.1.2)
        self.assertEqual(d.fill_grid.currentData(), "below")

        # the first sheet in the standard layout: its notes are checked below
        d.apply_settings(default_settings(self.prj, self.dem, self.pts, self.lines, h_scale=1000.0, v_scale=50.0,
                                          **STANDARD_LAYOUT))
        d.refresh()
        self.assertEqual(d.last_error, "")
        m, p = d.model, d.plan
        self.assertEqual([h.label for h in m.hits], ["B-1", "MW-1", "TP-1", "B-2", "MW-2", "CPT-1", "B-3"])
        self.assertEqual(sorted(m.beyond_ends), ["B-post", "B-pre"])

        # readouts
        line = d.line_readout.text()
        self.assertIn("Length <b>4,588 ft</b> · 3 vertices · 1 bend", line)
        self.assertIn("<b>E</b> (082°)", line)
        ground = d.ground_readout.text()
        self.assertIn("coverage <b>97%</b>", ground)
        self.assertIn("No DEM data:", ground)
        self.assertIn("Elevation units: feet (from the layer)", ground)
        explo = d.explo_readout.text()
        self.assertIn("Plotted <b>7</b>", explo)
        self.assertEqual(d.depth_readout.text(), "Tops: 3 ExploElev, 3 LIDAR, 1 none · Bottoms: 6 top − ExploDepth, 1 none")
        self.assertIn("Past the ends (left out): 2", explo)
        self.assertIn("MW-2: ExploElev 205.6 ft ignored", explo)
        self.assertIn("B-3: station in a DEM gap", explo)
        exp = d.export_readout.text()
        self.assertIn("VE <b>20×</b>", exp)
        self.assertIn("Sheet: <b>Letter", exp)
        self.assertTrue(d.message.isHidden(), d.message.text())      # every note is already in a readout
        counts = {d.type_list.topLevelItem(i).text(0): d.type_list.topLevelItem(i).text(1)
                  for i in range(d.type_list.topLevelItemCount())}
        self.assertEqual(counts["Boring"], "3 / 6")

        # preview and map
        self.check_preview(7)
        fb = d.feedback
        self.assertEqual(fb.line.numberOfVertices(), 3)
        self.assertGreater(fb.swath.numberOfVertices(), 4)
        self.assertEqual(fb.points.numberOfVertices(), 7)
        self.assertEqual([lab.text for lab in fb.labels], ["A", "A'"])

        # Export… PDF and PNG at 1 in = 1,000 ft H, 1 in = 50 ft V
        self.assertTrue(p.fits)
        self.assertEqual(len(p.pages), 1)
        page = p.pages[0]
        self.assertAlmostEqual(page.plot_w, 4.6)
        pdf = os.path.join(self.out, "A-A.pdf")
        self.assertEqual(export_via_dock(d, pdf, "PDF (*.pdf)"), [pdf])
        self.assertIn(pdf, self.iface.messageBar().currentItem().text())
        rd = self.check_pdf(pdf, p.pages, "green")
        text = rd.pages[0].extract_text()
        self.assertIn("1:12,000", text)
        self.assertIn("VERTICAL EXAGGERATION 20", text)
        self.assertIn("TD 60'", text)                     # CPT-1
        png = os.path.join(self.out, "A-A.png")
        self.assertEqual(export_via_dock(d, png, "PNG image (*.png)"), [png])
        self.check_png(png, page, "green")

        csv_path = os.path.join(self.out, "points.csv")
        with mock.patch("xsections.ui.dock.QFileDialog.getSaveFileName", return_value=(csv_path, "CSV (*.csv)")):
            self.assertEqual(d.export_points_csv(), csv_path)
        with open(csv_path, encoding="utf-8-sig") as fh:
            self.assertEqual(len(fh.read().strip().splitlines()), 1 + 7)

        # tiled: 1 in = 100 ft H, 1 in = 10 ft V on Tabloid, set through the widgets, in the default layout
        d.compact_layout.setChecked(True)
        d.fill_grid.setCurrentIndex(d.fill_grid.findData("below"))
        d.h_scale.setEditText("100")
        d.v_scale.setEditText("10")
        d.sheet.setCurrentIndex(d.sheet.findData("tabloid"))
        d.refresh()
        p = d.plan
        n = len(p.pages)
        self.assertTrue(p.fits, p.message)
        self.assertGreater(n, 1)
        self.assertTrue(all(pg.sheet_name.startswith("Tabloid") for pg in p.pages))
        self.assertEqual((p.h_major, p.v_major), (100.0, 10.0))
        self.assertIn(f"<b>{n} sheets</b>", d.export_readout.text())
        self.assertEqual(fb.ticks.numberOfVertices(), 2 * (n - 1))
        self.assertEqual(len([lab for lab in fb.labels if lab.text.startswith("MATCH ")]), n - 1)
        pv = self.check_preview(7)
        tags = [t.get_text() for a in pv.figure.axes for t in a.texts if t.get_gid() == SHEET_GID]
        self.assertEqual(len(tags), n)
        for i, tag in enumerate(tags, 1):        # "SHEET 2 OF 8", shortened to "8/8" on a short end sheet
            self.assertRegex(tag, rf"^(SHEET {i} OF {n}|SHEET {i}|{i}/{n}|{i})$")

        tiled = os.path.join(self.out, "A-A tiled.pdf")
        self.assertEqual(export_via_dock(d, tiled, "PDF (*.pdf)"), [tiled])
        rd = self.check_pdf(tiled, p.pages, "green", measure_pages=(1, n))
        for i, pg in enumerate(rd.pages, 1):
            self.assertIn(f"SHEET {i} OF {n}", re.sub(r"\s+", " ", pg.extract_text()))

        # settings went into the project
        from xsections.ui import settings_store
        saved = settings_store.load(QgsProject.instance())
        self.assertEqual((saved.h_scale, saved.v_scale, saved.sheet), (100.0, 10.0, "tabloid"))
        self.assertEqual((saved.compact_layout, saved.fill_grid), (True, "below"))

        self.check_unload()


# ------------------------------------------------------------------ QGIS's own plugin loader
class QgisPluginLoader(unittest.TestCase):
    """The folder is found, judged compatible, imported and started the way QGIS does it
    (qgis.utils), then unloaded. The repo root stands in for the profile's plugins folder."""

    def setUp(self):
        load_project()

    def test_find_start_unload(self):
        import importlib.util
        import sys
        import qgis
        import qgis.utils as qu
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        vc_path = os.path.join(os.path.dirname(os.path.dirname(qgis.__file__)), "pyplugin_installer",
                               "version_compare.py")
        spec = importlib.util.spec_from_file_location("_xsec_version_compare", vc_path)
        vc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vc)

        iface, mw = make_qgis_window()
        ours = {k: v for k, v in sys.modules.items() if k == "xsections" or k.startswith("xsections.")}
        saved = (list(qu.plugin_paths), list(qu.available_plugins), qu.iface)
        qu.plugin_paths[:] = [root]
        qu.iface = iface
        try:
            qu.updateAvailablePlugins()
            self.assertEqual(qu.available_plugins, ["xsections"])
            lo, hi = (qu.pluginMetadata("xsections", k) for k in ("qgisMinimumVersion", "qgisMaximumVersion"))
            self.assertTrue(vc.isCompatible(vc.pyQgisVersion(), lo, hi), (vc.pyQgisVersion(), lo, hi))
            self.assertEqual(qu.pluginMetadata("xsections", "name"), "XSections")
            self.assertTrue(qu.loadPlugin("xsections"))
            self.assertTrue(qu.startPlugin("xsections"))
            self.assertTrue(qu.isPluginLoaded("xsections"))
            plugin = qu.plugins["xsections"]
            iface.addToolBarIcon.assert_called_once_with(plugin.action)
            names = [d.objectName() for d in mw.findChildren(QgsDockWidget)]
            self.assertIn("XSectionsDock", names)
            self.assertIn("XSectionsPreviewDock", names)
            self.assertTrue(qu.unloadPlugin("xsections"))
            flush_deletes()
            self.assertFalse(qu.isPluginLoaded("xsections"))
            names = [d.objectName() for d in mw.findChildren(QgsDockWidget)]
            self.assertNotIn("XSectionsDock", names)
            iface.removeToolBarIcon.assert_called_once()
        finally:
            qu.plugin_paths[:], qu.available_plugins, qu.iface = saved
            if "xsections" in qu.plugins:
                qu.unloadPlugin("xsections")
            sys.modules.update(ours)          # unloadPlugin drops the modules; later tests still use them
            mw.close()
            mw.deleteLater()
            flush_deletes()


# ------------------------------------------------------------------ the user's data (copies)
@unittest.skipUnless(REALDATA, "set XSECTIONS_REALDATA to the copied real-data folder")
class RealDataEndToEnd(E2ECase):
    def setUp(self):
        self.realdata_state = folder_state(REALDATA)
        self.tmp = tempfile.mkdtemp(prefix="xsec_e2e_real_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        dem_path, wells_path = copy_realdata(self.tmp)
        self.out = os.path.join(self.tmp, "out")
        self.prj = QgsProject.instance()
        self.prj.clear()
        self.dem = QgsRasterLayer(dem_path, "cdf_lidar")
        self.wells = QgsVectorLayer(wells_path, "CDF_wells", "ogr")
        self.assertTrue(self.dem.isValid() and self.wells.isValid())
        self.prj.addMapLayers([self.dem, self.wells])
        self.prj.setCrs(self.dem.crs())
        self.addCleanup(self.prj.clear)

    def test_cdf_flow(self):
        self.open_plugin()
        d = self.dock
        # a fresh project: the panel guesses the layers and fields from their names
        self.assertIs(d.dem_layer.currentLayer(), self.dem)
        self.assertIs(d.points_layer.currentLayer(), self.wells)
        s = d.settings()
        self.assertEqual((s.label_field, s.type_field, s.top_field, s.bottom_elev_field, s.depth_field),
                         ("ExploName", "ExploType", "ExploElev", "", "ExploDepth"))
        self.assertTrue(s.td_label)
        self.assertEqual((s.compact_layout, s.edge_margin_in, s.show_notes, s.fill_grid), (True, 0.5, True, "below"))
        # the standard layout, whose notes are checked below (test_layout.RealDataDefaults checks this section's
        # sheet in the default layout)
        d.compact_layout.setChecked(False)
        d.fill_grid.setCurrentIndex(d.fill_grid.findData("off"))

        geom, tol = line_through_points(self.wells, self.dem.crs(), self.prj)
        d.tolerance.setValue(tol)
        d.h_scale.setEditText("200")
        d.v_scale.setEditText("20")
        d.set_drawn_line(geom, self.dem.crs())            # what the Draw on map tool hands over
        self.assertEqual(d.settings().line_crs_authid, "EPSG:4326")   # the LIDAR CRS has no authid
        d.refresh()
        self.assertEqual(d.last_error, "")
        m, p = d.model, d.plan
        self.assertAlmostEqual(m.length, geom.length() * m.dist_factor, delta=0.05)
        self.assertEqual(len(m.hits), 8)
        self.assertEqual(m.ground.coverage, 1.0)
        mw35 = {h.label: h for h in m.hits}["MW-35R"]
        self.assertEqual(mw35.top_source, "dem")
        self.assertTrue(any(f.startswith("ExploElev 205.6 ft ignored") for f in mw35.flags), mw35.flags)
        self.assertIn("MW-35R: ExploElev 205.6 ft ignored", d.explo_readout.text())
        self.assertIn("Plotted <b>8</b>", d.explo_readout.text())
        # no bottom elevations in this layer: every bottom is top - ExploDepth; MW-35R's top is LIDAR
        self.assertEqual(d.depth_readout.text(), "Tops: 7 ExploElev, 1 LIDAR · Bottoms: 8 top − ExploDepth")
        self.assertTrue(all(h.bottom_source == "depth" for h in m.hits))
        self.assertIn("assumed", d.message.text())          # the LIDAR does not state its z units
        self.assertIn("VE <b>10×</b>", d.export_readout.text())
        self.check_preview(8)
        self.assertEqual(d.feedback.points.numberOfVertices(), 8)

        self.assertTrue(p.fits, p.message)
        self.assertEqual(len(p.pages), 1)
        pdf = os.path.join(self.out, "CDF A-A.pdf")
        self.assertEqual(export_via_dock(d, pdf, "PDF (*.pdf)"), [pdf])
        rd = self.check_pdf(pdf, p.pages, "green")
        text = re.sub(r"\s+", " ", rd.pages[0].extract_text())
        self.assertIn("MW-35R", text)
        self.assertIn("TD 15'", text)                     # MW-35R is 15 ft deep
        note = ("Tops: ExploElev where available, otherwise LIDAR at the exploration. Bottoms: top minus "
                "ExploDepth. TD = total depth.")
        self.assertIn(note.replace(" ", ""), text.replace(" ", ""))    # (pypdf may split "Tops" as "T ops")
        png = os.path.join(self.out, "CDF A-A.png")
        self.assertEqual(export_via_dock(d, png, "PNG image (*.png)"), [png])
        self.check_png(png, p.pages[0], "green")

        self.check_unload()
        self.assertEqual(folder_state(REALDATA), self.realdata_state, "nothing written next to the originals")


if __name__ == "__main__":
    unittest.main()
