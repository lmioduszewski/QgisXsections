"""Export: files are written at exact scale, measured from their pixels (and PDF page boxes)."""
import os
import re
import shutil
import tempfile
import unittest

from tests.fixtures import start_app

start_app()

from pypdf import PdfReader                                               # noqa: E402

from tests import measure as M                                           # noqa: E402
from tests.test_figure import make_model, make_settings                  # noqa: E402
from xsections.core.model import SectionError                           # noqa: E402
from xsections.render.export import export, output_paths                # noqa: E402
from xsections.render.pdfprefs import read_print_prefs                  # noqa: E402
from xsections.render.scales import plan                                # noqa: E402


def _gdal_pdf_ok():
    try:
        from osgeo import gdal
        return gdal.GetDriverByName("PDF") is not None
    except Exception:
        return False


class ExportCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="xsec_export_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def check_png(self, path, page, dpi, grid, h_minor_in=0.1, v_minor_in=0.1, major_in=1.0):
        rgb, info = M.load_png(path)
        self.assertEqual(info["size"], (round(page.page_w * dpi), round(page.page_h * dpi)))
        self.assertIsNotNone(info["pHYs"])
        self.assertAlmostEqual(info["pHYs"]["dpi_x"], dpi, delta=0.01)
        self.assertAlmostEqual(info["pHYs"]["dpi_y"], dpi, delta=0.01)
        self.check_raster(rgb, page, dpi, grid, h_minor_in, v_minor_in, major_in)

    def check_raster(self, rgb, page, dpi, grid, h_minor_in=0.1, v_minor_in=0.1, major_in=1.0):
        m = M.measure(rgb, dpi, h_minor_in, v_minor_in, grid)
        for ax, inches in (("x", page.plot_w), ("y", page.plot_h)):
            d = m[ax]
            self.assertAlmostEqual(d["frame_px"], inches * dpi, delta=1.0, msg=f"{ax} frame")
            self.assertGreaterEqual(d["n_major"], 1, msg=f"{ax} majors")
            for sp in M.normalised_major_spacings(d["major_spacing_px"], major_in * dpi):
                self.assertAlmostEqual(sp, major_in * dpi, delta=0.5, msg=f"{ax} major spacing")
            self.assertAlmostEqual(d["px_per_in"], dpi, delta=0.05 * dpi / 300, msg=f"{ax} fitted px/in")
        return m

    def check_pdf(self, path, pages):
        rd = PdfReader(path)
        self.assertEqual(len(rd.pages), len(pages))
        for pg, layout in zip(rd.pages, pages):
            box = [float(v) for v in pg.mediabox]
            self.assertEqual(box, [0.0, 0.0, layout.page_w * 72, layout.page_h * 72])
        prefs = read_print_prefs(path)
        self.assertEqual(prefs.get("/PrintScaling"), "/None")
        self.assertIs(prefs.get("/PickTrayByPDFSize"), True)
        root = rd.trailer["/Root"].get_object()
        self.assertEqual(str(root.get("/Version")), "/1.7")
        return rd


class LetterExport(ExportCase):
    """4,500 ft at 1 in = 1,000 ft H and 1 in = 50 ft V on a Letter sheet."""

    def setUp(self):
        super().setUp()
        self.model = make_model()
        self.settings = make_settings(grid_color="gray", allowed_sheets=["letter"])
        self.plan = plan(self.model, self.settings)
        self.assertTrue(self.plan.fits, self.plan.message)
        self.page = self.plan.pages[0]
        self.assertEqual((self.page.page_w, self.page.page_h), (8.5, 11.0))
        self.assertEqual((self.page.plot_w, self.page.plot_h), (4.5, 7.0))

    def test_pdf(self):
        out = export(self.model, self.settings, self.plan, os.path.join(self.dir, "a.pdf"), "pdf")
        self.assertEqual(out, [os.path.join(self.dir, "a.pdf")])
        rd = self.check_pdf(out[0], self.plan.pages)
        text = rd.pages[0].extract_text()
        self.assertIn("CROSS SECTION", text)
        self.assertIn("1:12,000", text)
        if _gdal_pdf_ok():                                   # independent rasteriser
            rgb, _ = M.load_pdf_raster(out[0], 300)
            m = self.check_raster(rgb, self.page, 300, "gray")
            self.assertLess(m["x"]["max_residual_px"], 0.3)
            self.assertEqual(m["x"]["n_major"], 4)
            self.assertEqual(m["y"]["n_major"], 6)

    def test_png_300(self):
        out = export(self.model, self.settings, self.plan, os.path.join(self.dir, "a.png"), "png", 300)
        self.assertEqual(len(out), 1)
        self.check_png(out[0], self.page, 300, "gray")

    def test_png_600_green(self):
        s = make_settings(grid_color="green", allowed_sheets=["letter"])
        out = export(self.model, s, plan(self.model, s), os.path.join(self.dir, "g.png"), "png", 600)
        self.check_png(out[0], self.page, 600, "green")

    def test_svg(self):
        out = export(self.model, self.settings, self.plan, os.path.join(self.dir, "a.svg"), "svg")
        with open(out[0], encoding="utf-8") as fh:
            head = fh.read(3000)
        self.assertRegex(head, r'width="612(\.0+)?pt"')
        self.assertRegex(head, r'height="792(\.0+)?pt"')

    def test_refuses_when_not_fit(self):
        s = make_settings(h_scale=100.0, tile=False)
        p = plan(self.model, s)
        self.assertFalse(p.fits)
        with self.assertRaises(SectionError) as cm:
            export(self.model, s, p, os.path.join(self.dir, "x.pdf"))
        self.assertIn("The section needs a 47.5 × 10.5 in page", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "x.pdf")))

    def test_megapixel_limit(self):
        s = make_settings(sheet="archd")
        p = plan(self.model, s)
        with self.assertRaises(SectionError) as cm:
            export(self.model, s, p, os.path.join(self.dir, "big.png"), "png", 600)
        self.assertIn("megapixels", str(cm.exception))
        self.assertEqual(os.listdir(self.dir), [])

    def test_output_paths(self):
        self.assertEqual(output_paths("c:/x/sec.pdf", "pdf", 3), ["c:/x/sec.pdf"])
        self.assertEqual(output_paths("c:/x/sec.png", "png", 1), ["c:/x/sec.png"])
        self.assertEqual(output_paths("c:/x/sec.png", "png", 2), ["c:/x/sec_sheet1.png", "c:/x/sec_sheet2.png"])
        self.assertEqual(output_paths("c:/x/sec.pdf", "svg", 1), ["c:/x/sec.svg"])
        self.assertEqual(output_paths("c:/x/sec", "pdf", 1), ["c:/x/sec.pdf"])


class TiledExport(ExportCase):
    """4,600 ft at 1 in = 100 ft on Tabloid: several sheets with match lines."""

    def setUp(self):
        super().setUp()
        self.model = make_model(length=4600.0)
        self.settings = make_settings(h_scale=100.0, grid_color="gray", allowed_sheets=["tabloid"])
        self.plan = plan(self.model, self.settings)
        self.assertTrue(self.plan.fits, self.plan.message)
        self.assertEqual(len(self.plan.pages), 4)

    def test_pdf_pages_and_match_text(self):
        out = export(self.model, self.settings, self.plan, os.path.join(self.dir, "t.pdf"))
        rd = self.check_pdf(out[0], self.plan.pages)
        n = len(self.plan.pages)
        for i, (pg, layout) in enumerate(zip(rd.pages, self.plan.pages), 1):
            text = re.sub(r"\s+", " ", pg.extract_text())
            self.assertIn(f"SHEET {i} OF {n}", text)
            for m, other in ((layout.match_left, i - 1), (layout.match_right, i + 1)):
                if m is None:
                    continue
                sta = f"{int(m // 100)}+{int(m % 100):02d}"
                self.assertIn(f"MATCH LINE STA {sta}", text)
                self.assertIn(f"SEE SHEET {other} OF {n}", text)

    def test_png_every_sheet_to_scale(self):
        out = export(self.model, self.settings, self.plan, os.path.join(self.dir, "t.png"), "png", 300)
        self.assertEqual(len(out), len(self.plan.pages))
        for i, (path, page) in enumerate(zip(out, self.plan.pages), 1):
            self.assertTrue(path.endswith(f"t_sheet{i}.png"))
            self.check_png(path, page, 300, "gray")


class TopCapsAndTDLabelsToScale(ExportCase):
    """Top caps and TD labels (R2, R3) change nothing about the scale: the exported PNG still measures
    300 px per inch on both axes, and the PDF carries the TD text."""

    def setUp(self):
        super().setUp()
        self.model = make_model(td=True)
        self.settings = make_settings(title="TD labels")
        self.plan = plan(self.model, self.settings)
        self.assertTrue(self.plan.fits, self.plan.message)

    def test_png_300(self):
        out = export(self.model, self.settings, self.plan, os.path.join(self.dir, "td.png"), "png", 300)
        self.check_png(out[0], self.plan.pages[0], 300, "green")

    def test_pdf_text(self):
        out = export(self.model, self.settings, self.plan, os.path.join(self.dir, "td.pdf"))
        rd = self.check_pdf(out[0], self.plan.pages)
        text = re.sub(r"\s+", " ", rd.pages[0].extract_text())
        for h in self.model.hits:
            if h.total_depth is not None:
                self.assertIn(f"TD {h.total_depth:g}'", text)
        self.assertIn("TD = total depth.", text)


if __name__ == "__main__":
    unittest.main()
