"""His Explorations.gpkg (three point layers, 38,000 points) with the CDF LIDAR: the 0.3.3 rows on real data.

READ ONLY, always: the GeoPackage is byte-copied (shutil.copy2 only reads it) into the run's temp folder and only the
copy is opened (OGR on the copy, sqlite3 read-only on the copy); at the end the original must be unchanged (size,
modification time) with no new -wal / -shm / -journal file next to it. The LIDAR is the read-only real-data copy.

His file changes when he edits his data: the counts, labels, depths and dates below were measured on the file of
2026-08-25 (GPKG_SHA256). When the copy differs, those hard-number checks are skipped with a message; the structural,
read-only and budget checks still run.

Two parts. The core part (RealGeoPackageCore) builds the rows given explicitly, equal to the field guesses of the
panel. The panel part (RealGeoPackagePanel) opens the three layers in a fresh project, each test with its own project
and panel: the rows the panel guesses (and saves nothing), the supply wells running below the frame on the sheet, an
exploration left off through a project save and reload (and out of the points CSV), a PDF of the three rows, the
panel's budgets, and (0.3.4) AESI drawn in Color from his Cumberland style: the row's style box, following a
category switched off in QGIS.
"""
import csv
import hashlib
import os
import re
import shutil
import sqlite3
import tempfile
import time
import unittest
from collections import Counter
from unittest import mock

from tests.fixtures import (CUMBERLAND_AESI, GPKG, REALDATA, budget, categorized_renderer, point_row, rule_renderer,
                            start_app, timing_test, wait_ms)

APP = start_app()

from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from qgis.core import (Qgis, QgsFeatureRequest, QgsGeometry, QgsProject, QgsRasterLayer,  # noqa: E402
                       QgsVectorLayer)
from qgis.PyQt.QtCore import QCoreApplication, QEvent, QEventLoop, Qt, QTimer  # noqa: E402

from tests.test_ui import make_iface  # noqa: E402
from xsections.core import explorations as E  # noqa: E402
from xsections.core.build import build_section  # noqa: E402
from xsections.core.model import Settings, hidden_key, layer_rows, layer_view  # noqa: E402
from xsections.core.section import raster_sampler, resolve_line, section_crs  # noqa: E402
from xsections.render import figure as F  # noqa: E402
from xsections.render import scales as S  # noqa: E402
from xsections.ui import settings_store  # noqa: E402
from xsections.ui.dock import CSV_COLUMNS, XSectionsDock  # noqa: E402
from xsections.ui.point_rows import TypeList  # noqa: E402
from xsections.ui.preview import PreviewWidget  # noqa: E402

GPKG_SHA256 = "e54a8f7f29289524d151bcffab1ae2798c17aae533ed22da577ef47e0cadf456"   # the file of 2026-08-25
LAYERS = ("Explor_AESI_pt", "Explor_Other_pt", "Well_Supply_pt")
SIDECARS = ("-wal", "-shm", "-journal")
DENSE_LINE = "LineString (1217615.9 660688.6, 1216826.9 657744.0)"   # in the LIDAR's CRS; crosses TW-2
TOL = 150.0
HARD = "Explorations.gpkg differs from the file of 2026-08-25 (GPKG_SHA256): its counts, labels and dates were not "\
       "checked"


def _state(path):
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns, tuple(os.path.exists(path + s) for s in SIDECARS)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _sql_type_totals(path):
    """Features by ExploType_resolved for each layer, straight from the file (sqlite, read only, on the copy; NULL
    and '' are one "(no value)", as the panel counts them)."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        out = {}
        for name in LAYERS:
            tot = Counter()
            for value, n in con.execute(f'SELECT "ExploType_resolved", COUNT(*) FROM "{name}" '
                                        f'GROUP BY "ExploType_resolved"').fetchall():
                tot["" if value is None else str(value)] += n
            out[name] = tot
        return out
    finally:
        con.close()


def _wait(ms):
    """Run the event loop for `ms` (the panel's 300 ms rebuild timer), times fixtures.TIME_FACTOR."""
    loop = QEventLoop()
    QTimer.singleShot(wait_ms(ms), loop.quit)
    loop.exec()


def _pdf_text(path):
    """The text of every page with the whitespace taken out (pypdf may split a word, "T ops")."""
    return "".join(re.sub(r"\s+", "", pg.extract_text()) for pg in PdfReader(path).pages)


# the rows of the panel's field guesses (spec section 5) for his three layers
def aesi_row(layer, **kw):
    return point_row(layer, **dict(dict(label_field="ExploName", type_field="ExploType_resolved",
                                        top_field="ExploElev", depth_field="ExploDepth", wl_field="DepthToGW",
                                        wl_values="depth", wl_date_field="ExploDate"), **kw))


def other_row(layer, **kw):
    return point_row(layer, **dict(dict(label_field="ExploName", type_field="ExploType_resolved",
                                        top_field="ExploElev", depth_field="ExploDepth"), **kw))


def supply_row(layer, **kw):
    return point_row(layer, **dict(dict(label_field="AESI_MapLabel", type_field="ExploType_resolved",
                                        top_field="ExploElev", depth_field="WellCompleteDepth",
                                        atd_field="GW_Elev_ATD", atd_date_field="ExploDate", wl_values="elevation",
                                        in_range=False), **kw))


@unittest.skipUnless(REALDATA and os.path.isfile(GPKG),
                     "set XSECTIONS_REALDATA, and have his Explorations.gpkg (or XSECTIONS_GPKG)")
class RealGeoPackageCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = _state(GPKG)
        cls.dir = tempfile.mkdtemp(prefix="xsec_realgpkg_")
        cls.copy = os.path.join(cls.dir, "Explorations.gpkg")
        shutil.copy2(GPKG, cls.copy)                                       # reads the original, nothing else
        cls.same = _sha256(cls.copy) == GPKG_SHA256
        # the type totals straight from the file (sqlite, read only, on the copy; before OGR opens it)
        con = sqlite3.connect(f"file:{cls.copy}?mode=ro", uri=True)
        try:
            cls.sql_totals = {}
            for name in LAYERS:
                rows = con.execute(f'SELECT "ExploType_resolved", COUNT(*) FROM "{name}" '
                                   f'GROUP BY "ExploType_resolved"').fetchall()
                tot = Counter()
                for value, n in rows:
                    tot["" if value is None else str(value)] += n         # NULL and '' are one "(no value)"
                cls.sql_totals[name] = tot
            # (0.3.4) each AESI exploration's raw ExploType by fid (his Cumberland style is categorized on it)
            cls.aesi_types = dict(con.execute('SELECT "id", "ExploType" FROM "Explor_AESI_pt"').fetchall())
        finally:
            con.close()
        prj = cls.prj = QgsProject.instance()
        prj.clear()
        cls.L = {n: QgsVectorLayer(f"{cls.copy}|layername={n}", n, "ogr") for n in LAYERS}
        cls.dem = QgsRasterLayer(os.path.join(REALDATA, "cdf_lidar.tif"), "cdf_lidar")
        assert cls.dem.isValid() and all(lyr.isValid() for lyr in cls.L.values())
        prj.addMapLayers(list(cls.L.values()) + [cls.dem])
        prj.setCrs(cls.dem.crs())

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().clear()

    def settings(self, rows, **kw):
        return Settings(dem_layer_id=self.dem.id(), line_wkt=DENSE_LINE, line_crs_authid=self.dem.crs().toWkt(),
                        tolerance_ft=TOL, point_layers=list(rows), **kw)

    def rows(self):
        return [aesi_row(self.L["Explor_AESI_pt"]), other_row(self.L["Explor_Other_pt"]),
                supply_row(self.L["Well_Supply_pt"])]

    def test_layers(self):
        for name, lyr in self.L.items():
            self.assertEqual(lyr.geometryType(), Qgis.GeometryType.Point, name)
            self.assertEqual([lyr.fields().at(i).name() for i in lyr.primaryKeyAttributes()], ["id"], name)
            self.assertEqual(lyr.featureCount(), sum(self.sql_totals[name].values()), name)
        self.assertTrue(self.L["Explor_AESI_pt"].fields().field("ExploDate").isNumeric())   # epoch milliseconds

    @timing_test
    def test_three_rows(self):
        t = time.perf_counter()
        m = build_section(self.settings(self.rows()), self.prj)
        dt = time.perf_counter() - t
        self.assertLessEqual(dt, budget(1.5), f"3-row build took {dt:.3f} s")
        self.assertEqual([i.on for i in m.point_layers], [True, True, True])
        self.assertEqual([i.name for i in m.point_layers], list(LAYERS))
        self.assertEqual(len(m.hits), sum(i.plotted for i in m.point_layers))
        self.assertEqual([(h.station, h.layer_index, h.label) for h in m.hits],
                         sorted((h.station, h.layer_index, h.label) for h in m.hits))
        self.assertTrue(all(h.in_range == (h.layer_index != 2) for h in m.hits))
        print(f"\n  his gpkg, 3 rows: {[i.plotted for i in m.point_layers]} plotted in {dt:.3f} s")
        if not self.same:
            self.skipTest(HARD)
        self.assertEqual([i.plotted for i in m.point_layers], [38, 7, 1])
        self.assertEqual(len(m.hits), 46)
        by = {}
        for h in m.hits:
            by.setdefault(h.label, []).append(h)
        self.assertEqual([h.layer_index for h in by["TW-2"]], [0])
        self.assertEqual([h.layer_index for h in by["D-447 (TW-2)"]], [2])     # both plotted (decision 4)
        d447 = by["D-447 (TW-2)"][0]
        self.assertEqual(d447.total_depth, 280.0)                               # WellCompleteDepth
        self.assertEqual(d447.water_levels, [])                                 # GW_Elev_ATD 0: none
        self.assertAlmostEqual(d447.bottom, 394.2, delta=0.05)
        self.assertEqual([(w.kind, w.date) for w in by["EB-118W"][0].water_levels], [("measured", "12/9/2024")])
        self.assertEqual([(w.kind, w.date) for w in by["MW-34"][0].water_levels], [("measured", "2/2/2021")])
        others = [h for h in m.hits if h.layer_index == 1]
        self.assertEqual(sum(any(f.startswith("no bottom elevation or depth") for f in h.flags) for h in others), 6)

    @timing_test
    def test_find_explorations_budget(self):
        s = self.settings(self.rows()[:1])
        crs = section_crs(self.dem, self.prj)
        line = resolve_line(s, self.prj, crs)
        sampler = raster_sampler(self.dem, 1, crs, 1.0)
        t = time.perf_counter()
        hits, _, _ = E.find_explorations(line, self.L["Explor_AESI_pt"], layer_view(s, layer_rows(s)[0]), crs,
                                         sampler, 1.0, self.prj)
        dt = time.perf_counter() - t
        self.assertLessEqual(dt, budget(0.5),
                             f"find_explorations on {self.L['Explor_AESI_pt'].featureCount()} points: {dt:.3f} s")
        self.assertTrue(hits)

    def test_type_totals_match_the_file(self):
        """The totals by type read through QGIS (NULL and '' as one value) equal a GROUP BY on the file, and the
        type filter's "(no value)" ("") selects exactly the NULL-or-empty ones."""
        req = lambda: QgsFeatureRequest().setFlags(Qgis.FeatureRequestFlag.NoGeometry)   # noqa: E731
        for name, lyr in self.L.items():
            i = lyr.fields().lookupField("ExploType_resolved")
            tot = Counter()
            for f in lyr.getFeatures(req().setSubsetOfAttributes([i])):
                v = f.attribute(i)
                tot["" if v is None or (hasattr(v, "isNull") and v.isNull()) else str(v)] += 1
            self.assertEqual(tot, self.sql_totals[name], name)
            for types in ([""], ["", sorted(k for k in tot if k)[0]]):
                expr = E._type_filter(lyr, i, types)
                n = sum(1 for _ in lyr.getFeatures(req().setNoAttributes().setFilterExpression(expr)))
                self.assertEqual(n, sum(tot[t] for t in types), (name, types))
        if not self.same:
            self.skipTest(HARD)
        self.assertEqual(self.sql_totals["Well_Supply_pt"][""], 418)
        self.assertEqual(self.sql_totals["Well_Supply_pt"]["SPRING WELL , GRP A/B/DOM"], 16)
        self.assertEqual(len([k for k in self.sql_totals["Explor_AESI_pt"] if k]), 12)

    def test_a_row_out_of_the_range(self):
        """AESI ticked to EXPLORATION PIT only, the Other row off: D-447 of the supply wells (out of the range)
        reaches below the frame set by the AESI row (the frame is the plan without the supply row)."""
        rows = self.rows()
        rows[0] = dict(rows[0], types=["EXPLORATION PIT"])
        rows[1] = dict(rows[1], visible=False)
        s = self.settings(rows, fill_grid="off")
        m = build_section(s, self.prj)
        alone = self.settings(rows[:1], fill_grid="off")
        frame = S.plan(build_section(alone, self.prj), alone).z_min
        supply = [h for h in m.hits if h.layer_index == 2]
        self.assertTrue(supply and all(not h.in_range for h in supply))
        self.assertEqual({h.type_value for h in m.hits if h.layer_index == 0}, {"EXPLORATION PIT"})
        runs_below = getattr(S, "runs_below", None)                        # render (stage B) and later
        if runs_below is not None:
            z_min = S.plan(m, s).z_min
            self.assertEqual(z_min, frame)                                  # out of the range: the same frame
            self.assertTrue([h for h in supply if runs_below(h, z_min, s)])
        if not self.same:
            self.skipTest(HARD)
        d447 = next(h for h in supply if h.label == "D-447 (TW-2)")
        self.assertAlmostEqual(d447.bottom, 394.2, delta=0.05)
        self.assertLess(d447.bottom, frame)
        if runs_below is not None:
            self.assertTrue(runs_below(d447, frame, s))

    # ------------------------------------------------------------------ 0.3.4: Color from the layer's style
    def styled(self, renderer):
        """AESI drawn with `renderer` for this test (its own renderer back afterwards)."""
        lyr = self.L["Explor_AESI_pt"]
        self.addCleanup(lyr.setRenderer, lyr.renderer().clone())
        lyr.setRenderer(renderer)

    def color_rows(self):
        rows = self.rows()
        rows[0] = dict(rows[0], look="color")
        return rows

    def test_aesi_in_color_from_his_cumberland_style(self):
        """His Cumberland style (categorized by ExploType): every AESI exploration takes its category's colour (its
        ExploType read by fid with sqlite on the copy); NULL, empty or a value with no category: the NULL category,
        the catch-all, #e049db. The other two rows stay black."""
        self.styled(categorized_renderer("ExploType", CUMBERLAND_AESI))
        m = build_section(self.settings(self.color_rows()), self.prj)
        info = m.point_layers[0]
        self.assertEqual((info.look, info.style.kind, info.style.field), ("color", "categorized", "ExploType"))
        self.assertEqual(len(info.style.items), 13)
        self.assertEqual([(i.label, i.color) for i in info.style.items],
                         [(lab or "(no value)", c) for _v, lab, c in CUMBERLAND_AESI])
        cats = {v: (i, c) for i, (v, _lab, c) in enumerate(CUMBERLAND_AESI) if v}
        catch_all = (len(CUMBERLAND_AESI) - 1, "#e049db")
        aesi = [h for h in m.hits if h.layer_index == 0]
        self.assertTrue(aesi)
        for h in aesi:
            v = self.aesi_types[h.fid]
            want = cats.get(v, catch_all) if v not in (None, "") else catch_all
            self.assertEqual((h.style_rank, h.color), want, (h.label, v))
        self.assertEqual({(h.look, h.style_rank, h.color) for h in m.hits if h.layer_index != 0},
                         {("black", -1, "")})
        if not self.same:
            self.skipTest(HARD)
        tw2 = next(h for h in aesi if h.label == "TW-2")
        self.assertEqual((self.aesi_types[tw2.fid], tw2.color), ("MW, EB-1W, TW, OBW", "#3fcaa2"))

    def test_aesi_in_color_from_rules(self):
        """Rule-based as his Tehaleh project: two rules on ("MW, EB-1W, TW, OBW", "UIC WELL, DD"), the others and an
        ELSE off: only those two types are coloured, the rest draw nothing (-1, "": black on the sheet)."""
        on = {"MW, EB-1W, TW, OBW", "UIC WELL, DD"}
        rules = [(f"\"ExploType\" = '{v}'", lab, c, v in on) for v, lab, c in CUMBERLAND_AESI if v]
        self.styled(rule_renderer(rules + [("ELSE", "Other", "#987db7", False)]))
        m = build_section(self.settings(self.color_rows()), self.prj)
        st = m.point_layers[0].style
        self.assertEqual((st.kind, len(st.items)), ("rule", 13))
        self.assertEqual(sum(not i.on for i in st.items), 11)
        index = {i.label: n for n, i in enumerate(st.items)}
        aesi = [h for h in m.hits if h.layer_index == 0]
        for h in aesi:
            v = self.aesi_types[h.fid]
            want = (index[v], dict((x, c) for x, _lab, c in CUMBERLAND_AESI)[v]) if v in on else (-1, "")
            self.assertEqual((h.style_rank, h.color), want, (h.label, v))
        if not self.same:
            self.skipTest(HARD)
        self.assertIn("MW, EB-1W, TW, OBW", {self.aesi_types[h.fid] for h in aesi})
        self.assertTrue([h for h in aesi if h.style_rank == -1])

    @timing_test
    def test_three_rows_with_aesi_in_color(self):
        """The 3-row budget (1.5 s) with AESI in Color."""
        self.styled(categorized_renderer("ExploType", CUMBERLAND_AESI))
        t = time.perf_counter()
        m = build_section(self.settings(self.color_rows()), self.prj)
        dt = time.perf_counter() - t
        self.assertLessEqual(dt, budget(1.5), f"3-row build with AESI in Color took {dt:.3f} s")
        self.assertTrue(all(h.color for h in m.hits if h.layer_index == 0))
        print(f"\n  his gpkg, 3 rows, AESI in Color: {dt:.3f} s")

    def test_aesi_in_color_on_the_sheet(self):
        """(render) His Cumberland style on AESI in Color: the legend lists the categories of the plotted AESI
        explorations that have a depth line, in the style's order and as the layer's legend names them (kind
        "style"); the two Black rows are listed by name (drawn differently); a PDF has "Legend:" and those labels;
        names and ticks stay black."""
        from matplotlib.text import Annotation
        from xsections.render.export import export
        self.styled(categorized_renderer("ExploType", CUMBERLAND_AESI))
        s = self.settings(self.color_rows())
        m = build_section(s, self.prj)
        items = m.point_layers[0].style.items
        ranks = sorted({h.style_rank for h in m.hits if h.layer_index == 0 and h.color and S.draws_depth_line(h, s)})
        self.assertTrue(ranks)
        want = [(items[r].label, items[r].color) for r in ranks]
        order = [lab or "(no value)" for _v, lab, _c in CUMBERLAND_AESI]
        self.assertEqual([lab for lab in order if lab in {w[0] for w in want}], [w[0] for w in want])   # its order
        entries = S.legend_entries(m, s)
        self.assertEqual([(e.text, e.color, e.key) for e in entries if e.kind == "style"],
                         [(lab, c, 0) for lab, c in want])
        drawn_rows = [i for i in (1, 2) if any(h.layer_index == i for h in m.hits)]
        self.assertEqual([e.text for e in entries if e.kind == "layer"], [m.point_layers[i].name for i in drawn_rows])
        p = S.plan(m, s)
        fig = Figure()
        FigureCanvasAgg(fig)
        F.draw_page(fig, m, s, p, p.pages[0])
        ax = fig.axes[0]
        self.assertEqual({ln.get_color() for ln in ax.lines if ln.get_marker() == "|"}, {F.INK})
        names = {h.label for h in m.hits}
        self.assertEqual({a.get_color() for a in ax.texts if isinstance(a, Annotation) and a.get_text() in names},
                         {F.INK})
        pdf = os.path.join(tempfile.mkdtemp(prefix="xsec_realgpkg_color_"), "color.pdf")
        export(m, s, p, pdf, "pdf")
        text = _pdf_text(pdf)
        self.assertIn("Legend:", text)
        for lab, _c in want:
            self.assertIn(re.sub(r"\s+", "", lab), text)
        if not self.same:
            self.skipTest(HARD)
        self.assertIn("MW, EB-1W, TW, OBW", [w[0] for w in want])                # TW-2

    def test_z_original_unchanged(self):
        """(Runs last.) The original GeoPackage is as it was, with no new file next to it."""
        after = _state(GPKG)
        self.assertEqual(after[:2], self.before[:2])
        self.assertFalse(any(a and not b for a, b in zip(after[2], self.before[2])), after)


AESI, OTHER, SUPPLY = LAYERS


@unittest.skipUnless(REALDATA and os.path.isfile(GPKG),
                     "set XSECTIONS_REALDATA, and have his Explorations.gpkg (or XSECTIONS_GPKG)")
class RealGeoPackagePanel(unittest.TestCase):
    """The panel on a fresh project holding his three layers and the CDF LIDAR (nothing saved in it yet). Each test
    gets its own project, opened from one byte copy of the GeoPackage, and its own panel; the section line is the
    dense line, drawn on the map."""

    @classmethod
    def setUpClass(cls):
        cls.before = _state(GPKG)
        cls.realdata = sorted(os.listdir(REALDATA))
        cls.dir = tempfile.mkdtemp(prefix="xsec_realgpkg_panel_")
        cls.copy = os.path.join(cls.dir, "Explorations.gpkg")
        shutil.copy2(GPKG, cls.copy)                                       # reads the original, nothing else
        cls.same = _sha256(cls.copy) == GPKG_SHA256
        cls.sql_totals = _sql_type_totals(cls.copy)                         # before OGR opens the copy

    def setUp(self):
        prj = self.prj = QgsProject.instance()
        prj.clear()
        self.addCleanup(self._clear)                                      # (runs after the panels are gone)
        self.L = {n: QgsVectorLayer(f"{self.copy}|layername={n}", n, "ogr") for n in LAYERS}
        self.dem = QgsRasterLayer(os.path.join(REALDATA, "cdf_lidar.tif"), "cdf_lidar")
        self.assertTrue(self.dem.isValid() and all(lyr.isValid() for lyr in self.L.values()))
        prj.addMapLayers(list(self.L.values()) + [self.dem])
        prj.setCrs(self.dem.crs())
        prj.setDirty(False)
        self.iface = make_iface()

    def _clear(self):
        self.prj.clear()
        APP.processEvents()

    def new_dock(self, preview=False) -> XSectionsDock:
        """A panel opened on the fresh project (its rows guessed from the layer names)."""
        pv = PreviewWidget() if preview else None
        d = XSectionsDock(self.iface, pv)

        def drop():
            d.cleanup()
            d.deleteLater()
            if pv is not None:
                pv.deleteLater()
            APP.processEvents()
        self.addCleanup(drop)
        d.restore_from_project()
        return d

    def row(self, d, name):
        return next(r for r in d.explo_rows if r.layer() is self.L[name])

    def draw(self, d):
        """The dense line, as the Draw on map tool hands it over (in the LIDAR's CRS)."""
        d.set_drawn_line(QgsGeometry.fromWkt(DENSE_LINE), self.dem.crs())

    def all_on(self, d):
        """The line drawn and the supply wells ticked on (they start unticked): the 3-row section."""
        self.draw(d)
        self.row(d, SUPPLY).visible_box.setChecked(True)
        d.refresh()
        self.assertEqual(d.last_error, "")
        self.assertEqual([i.on for i in d.model.point_layers], [True, True, True])

    def test_fresh_project_guesses(self):
        """A row per layer, in the layers panel's order with the supply wells last, each with the fields of section
        5's guesses (never the GeoPackage fid `id`); the supply wells unticked and out of the elevation range, every
        type ticked, "(no value)" too; the type totals of each row equal a GROUP BY on the file. Guesses only:
        nothing is saved and the project stays clean."""
        d = self.new_dock()
        tree = [n.layer() for n in self.prj.layerTreeRoot().findLayers()]
        named = [lyr for lyr in tree if lyr in (self.L[AESI], self.L[OTHER])]
        self.assertEqual([r.layer() for r in d.explo_rows], named + [self.L[SUPPLY]])
        self.assertEqual(d.other_rows, [])                                 # no layer named like seeps or springs
        s = d.settings()
        self.assertEqual(s.dem_layer_id, self.dem.id())
        want = {AESI: aesi_row(self.L[AESI]), OTHER: other_row(self.L[OTHER]),
                SUPPLY: supply_row(self.L[SUPPLY], visible=False)}
        rows = layer_rows(s)
        self.assertEqual(rows, [want[r.layer().name()] for r in d.explo_rows])
        for row in rows:
            self.assertNotIn("id", [v for k, v in row.items() if k.endswith("_field")])
        sup = self.row(d, SUPPLY)
        self.assertEqual((rows[-1]["visible"], rows[-1]["in_range"], rows[-1]["types"]), (False, False, []))
        ticks = dict(sup.type_list.values())
        self.assertTrue(ticks and all(ticks.values()), ticks)               # every type ticked ...
        self.assertIn("", ticks)                                            # ... "(no value)" among them
        self.assertEqual(sup.type_list.item_for("").text(0), "(no value)")
        for r in d.explo_rows:
            name = r.layer().name()
            self.assertEqual(r.type_list.totals, self.sql_totals[name], name)
        self.assertFalse(d._user_changed)
        self.assertEqual(settings_store.stored_json(self.prj), "")
        self.assertFalse(self.prj.isDirty())
        if not self.same:
            self.skipTest(HARD)
        self.assertEqual(sup.type_list.totals[""], 418)
        spring = sup.type_list.item_for("SPRING WELL , GRP A/B/DOM")
        self.assertEqual((spring.checkState(0), sup.type_list.totals[spring.data(0, TypeList.VALUE)]),
                         (Qt.CheckState.Checked, 16))

    def test_below_the_frame_on_the_sheet(self):
        """AESI ticked to EXPLORATION PIT only, the Other row off, the supply wells ticked on, no grid fill: D-447
        of the supply wells (out of the elevation range) reaches below the frame. The sheet draws it to the frame,
        with the arrow and its TD beside it, and the panel says so."""
        d = self.new_dock()
        self.draw(d)
        aesi = self.row(d, AESI)
        self.row(d, SUPPLY).visible_box.setChecked(True)
        self.row(d, OTHER).visible_box.setChecked(False)
        aesi.btn_types_none.click()
        aesi.type_list.item_for("EXPLORATION PIT").setCheckState(0, Qt.CheckState.Checked)
        d.fill_grid.setCurrentIndex(d.fill_grid.findData("off"))
        d.refresh()
        self.assertEqual(d.last_error, "")
        s, m, p = d._settings, d.model, d.plan
        self.assertEqual(layer_rows(s)[d.explo_rows.index(aesi)]["types"], ["EXPLORATION PIT"])
        self.assertEqual({h.type_value for h in m.hits if h.layer_id == self.L[AESI].id()}, {"EXPLORATION PIT"})
        self.assertFalse([h for h in m.hits if h.layer_id == self.L[OTHER].id()])
        below = [h for h in m.hits if h.layer_id == self.L[SUPPLY].id() and S.runs_below(h, p.z_min, s)]
        self.assertTrue(below)
        h = below[0]
        page = next(pg for pg in p.pages if pg.x_min <= h.station <= pg.x_max)
        fig = Figure(figsize=(page.page_w, page.page_h), dpi=72)
        FigureCanvasAgg(fig)
        F.draw_page(fig, m, s, p, page)
        ax = fig.axes[0]
        self.assertIn(h.station, [a.get_xdata()[1] for a in ax.lines if a.get_gid() == F.CLIP_GID])   # the arrow
        at = [list(ln.get_ydata()) for ln in ax.lines if ln.get_gid() is None and ln.get_marker() == "None"
              and list(ln.get_xdata()) == [h.station, h.station]]
        self.assertIn([h.top, p.z_min], at)                                         # its line stops at the frame
        tds = [t.get_text() for t in ax.texts if t.get_gid() == F.CLIP_TD_GID]
        self.assertIn(S.td_text(h.total_depth), tds)
        self.assertIn("below the frame", d.explo_readout.text())
        if not self.same:
            self.skipTest(HARD)
        self.assertEqual([x.label for x in below], ["D-447 (TW-2)"])
        self.assertAlmostEqual(h.bottom, 394.2, delta=0.05)
        self.assertIn("TD 280'", tds)
        self.assertIn(f" · <span style='color:{d._warn_color()}'>D-447 (TW-2) runs below the frame (TD 280′)"
                      "</span>", d.explo_readout.text())

    def test_left_off_kept_with_the_project(self):
        """Untick one exploration in Plotted explorations, save the project, open it again (the plugin restores the
        panel from it): still left off, and absent from the points CSV, which names each one's layer."""
        from xsections import classFactory
        plugin = classFactory(self.iface)
        plugin.initGui()
        self.addCleanup(plugin.unload)
        d = plugin.dock
        self.all_on(d)
        n = len(d.model.hits)
        h = d.model.hits[0]
        key = (h.layer_id, h.fid)
        d.plotted.item_for(h.layer_id, h.fid).setCheckState(0, Qt.CheckState.Unchecked)
        d.refresh()                                                      # saves his change, rebuilds
        self.assertEqual([(x.layer_id, x.fid) for x in d.model.left_off], [key])
        hidden = d.settings().hidden_points
        self.assertEqual(hidden, [hidden_key("drawn", h.layer_id, h.fid)])
        rows = layer_rows(d.settings())
        path = os.path.join(tempfile.mkdtemp(prefix="xsec_realgpkg_prj_"), "sections.qgs")
        self.assertTrue(self.prj.write(path))
        self.prj.clear()
        self.assertEqual(d.explo_rows, [])
        self.assertTrue(self.prj.read(path))
        self.assertEqual(layer_rows(d.settings()), rows)
        self.assertEqual(d.settings().hidden_points, hidden)
        d.refresh()
        self.assertEqual(d.last_error, "")
        self.assertEqual([(x.layer_id, x.fid) for x in d.model.left_off], [key])
        self.assertNotIn(key, [(x.layer_id, x.fid) for x in d.model.hits])
        self.assertEqual(len(d.model.hits), n - 1)
        self.assertEqual(d.plotted.text(), f"Plotted explorations ({n - 1} of {n}, 1 left off by you)")
        out = os.path.join(tempfile.mkdtemp(prefix="xsec_realgpkg_csv_"), "points.csv")
        with mock.patch("xsections.ui.dock.QFileDialog.getSaveFileName", return_value=(out, "CSV (*.csv)")):
            self.assertEqual(d.export_points_csv(), out)
        with open(out, newline="", encoding="utf-8-sig") as fh:
            table = list(csv.reader(fh))
        self.assertEqual(table[0], CSV_COLUMNS)
        self.assertEqual(Counter((r[0], r[-1]) for r in table[1:]),
                         Counter((x.label, x.layer_name) for x in d.model.hits))     # the plotted ones only
        self.assertEqual({r[-1] for r in table[1:]}, set(LAYERS))
        if not self.same:
            self.skipTest(HARD)
        self.assertEqual(n, 46)

    def test_pdf_of_the_three_rows(self):
        """A PDF of the 3-row section: every plotted label of the three layers is on it; all three layers are drawn
        in Black, so the legend lists no layers."""
        d = self.new_dock()
        self.all_on(d)
        m, s = d.model, d._settings
        self.assertEqual([e.text for e in S.legend_entries(m, s) if e.kind == "layer"], [])
        swatches = []
        real = F.draw_swatch

        def record(fig, model, settings, entry, x, y):
            swatches.append(entry)
            return real(fig, model, settings, entry, x, y)
        pdf = os.path.join(tempfile.mkdtemp(prefix="xsec_realgpkg_pdf_"), "section.pdf")
        with mock.patch.object(F, "draw_swatch", side_effect=record), \
                mock.patch("xsections.ui.dock.QFileDialog.getSaveFileName", return_value=(pdf, "PDF (*.pdf)")):
            self.assertEqual(d.export_section(), [pdf])
        self.assertEqual([e for e in swatches if getattr(e, "kind", "type") == "layer"], [])
        text = _pdf_text(pdf)
        for info in m.point_layers:
            labels = sorted({h.label for h in m.hits if h.layer_index == info.index})
            self.assertEqual([lab for lab in labels if re.sub(r"\s+", "", lab) not in text], [], info.name)
        if not self.same:
            self.skipTest(HARD)
        self.assertEqual({i.name: i.plotted for i in m.point_layers}, {AESI: 38, OTHER: 7, SUPPLY: 1})
        self.assertIn("D-447(TW-2)", text)
        self.assertEqual({sec.title(): sec.chipText() for sec in d.sections}["Explorations"], "3 of 3 on · 46 plotted")

    @timing_test
    def test_budgets(self):
        """TypeList.fill of AESI <= 0.75 s; a refresh of the 3-row section with the preview <= 3.0 s; one tick in
        Plotted explorations: exactly one rebuild and no type scan (a getFeatures call without geometry)."""
        tl = TypeList()
        self.addCleanup(tl.deleteLater)
        t = time.perf_counter()
        tl.fill(self.L[AESI], "ExploType_resolved", [])
        dt = time.perf_counter() - t
        self.assertLessEqual(dt, budget(0.75), f"TypeList.fill of {self.L[AESI].featureCount()} points: {dt:.3f} s")
        self.assertEqual(tl.totals, self.sql_totals[AESI])
        d = self.new_dock(preview=True)
        self.all_on(d)
        t = time.perf_counter()
        d.refresh()
        d.preview.render_pending()
        dt = time.perf_counter() - t
        print(f"\n  his gpkg: refresh of the 3-row section with the preview: {dt:.3f} s")
        self.assertLessEqual(dt, budget(3.0))
        scans = Counter()
        for lyr in self.L.values():
            def counting(request=None, *args, _lyr=lyr, _orig=lyr.getFeatures):
                if request is not None and hasattr(request, "flags") \
                        and request.flags() & Qgis.FeatureRequestFlag.NoGeometry:
                    scans[_lyr.name()] += 1
                return _orig(request, *args) if request is not None else _orig()
            p = mock.patch.object(lyr, "getFeatures", side_effect=counting)
            p.start()
            self.addCleanup(p.stop)
        builds = []
        real = d._pipeline
        d._pipeline = lambda s: (builds.append(1), real(s))[1]
        d.resize(340, 700)
        d.show()
        APP.processEvents()
        d.refresh()
        # (0.3.5) the widgets earlier tests handed to deleteLater are deleted by the first event loop that runs: here,
        # not inside the timed wait below (thousands of them starve the panel's 300 ms timer on a busy machine)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        builds.clear()
        scans.clear()
        h = d.model.hits[0]
        d.plotted.item_for(h.layer_id, h.fid).setCheckState(0, Qt.CheckState.Unchecked)
        _wait(700)
        d.hide()
        self.assertEqual(len(builds), 1)
        self.assertEqual(scans, Counter())
        self.assertEqual([(x.layer_id, x.fid) for x in d.model.left_off], [(h.layer_id, h.fid)])

    def test_aesi_in_color_style_box(self):
        """(0.3.4, panel) AESI with his Cumberland style (categorized by ExploType) and its row switched to Color: the
        style box names the style and its 13 categories, shows 4 chips (the categories plotted on the dense line
        first, in the style's order), "+ 9 more" and the foot. A plotted category switched off in the renderer and
        styleChanged: the box says so, the section is rebuilt (nothing saved) and those explorations are black."""
        lyr = self.L[AESI]
        lyr.setRenderer(categorized_renderer("ExploType", CUMBERLAND_AESI))
        d = self.new_dock()
        self.draw(d)
        row = self.row(d, AESI)
        i = d.explo_rows.index(row)
        row.look_seg.buttons()[row.look_seg.findData("color")].click()             # his choice
        d.refresh()
        self.assertEqual(d.last_error, "")
        box = row.style_box
        self.assertFalse(box.isHidden())
        self.assertEqual(box.head.text(), "From the layer's style in QGIS: <b>Categorized by ExploType</b> · 13 "
                                          "categories")
        st = d.model.point_layers[i].style
        self.assertEqual([(it.label, it.color) for it in st.items],
                         [(lab or "(no value)", c) for _v, lab, c in CUMBERLAND_AESI])
        ranks = sorted({h.style_rank for h in d.model.hits if h.layer_index == i and h.style_rank >= 0})
        self.assertTrue(ranks)
        order = ranks + [r for r in range(len(st.items)) if r not in ranks]
        self.assertEqual(box.chips.items(), [(st.items[r].label, st.items[r].color) for r in order[:4]])
        self.assertEqual((box.chips.more(), box.off_note.isHidden(), box.foot.isHidden()), (9, True, False))
        self.assertEqual(row.swatch.colors(), [st.items[r].color for r in order[:3]])
        self.assertFalse(d._user_changed)                                            # (saved by the refresh)
        # a plotted category switched off in the Layers panel
        off = ranks[0]
        d._timer.stop()
        d._stale = False
        lyr.renderer().checkLegendSymbolItem(st.items[off].key, False)
        lyr.emitStyleChanged()
        self.assertEqual(box.off_note.text(), "1 switched off in QGIS: their explorations are drawn in black.")
        self.assertNotIn((st.items[off].label, st.items[off].color), box.chips.items())
        self.assertEqual(box.chips.more(), 8)
        self.assertTrue(d._stale and d._timer.isActive())
        self.assertFalse(d._user_changed)
        d.refresh()
        gone = [h for h in d.model.hits if h.layer_index == i and h.style_rank == -1]
        self.assertTrue(gone)
        self.assertEqual({h.color for h in gone}, {""})
        self.assertNotIn(off, {h.style_rank for h in d.model.hits if h.layer_index == i})

    def test_z_original_unchanged(self):
        """(Runs last.) The original GeoPackage is as it was, with no new file next to it, and nothing was written
        into the real-data folder."""
        after = _state(GPKG)
        self.assertEqual(after[:2], self.before[:2])
        self.assertFalse(any(a and not b for a, b in zip(after[2], self.before[2])), after)
        self.assertEqual(sorted(os.listdir(REALDATA)), self.realdata)


if __name__ == "__main__":
    unittest.main()
