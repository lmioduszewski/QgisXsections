"""Print preferences on a QGIS without pypdf: our own incremental update, checked with pypdf.

pypdf is hidden by putting None in sys.modules['pypdf'] (then 'import pypdf' raises ImportError).
The PDFs are the exporter's own (matplotlib, classic xref table), plus one rewritten so the catalog
sits in an object stream behind an xref stream, the way Ghostscript and Acrobat save.
"""
import contextlib
import logging
import os
import shutil
import sys
import tempfile
import unittest
import zlib
from unittest import mock

from tests.fixtures import start_app

start_app()

import numpy as np  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402
from pypdf.generic import BooleanObject, DictionaryObject, NameObject  # noqa: E402

from tests import measure as M  # noqa: E402
from tests.test_figure import make_model, make_settings  # noqa: E402
from xsections.render import _pdf_incremental as inc  # noqa: E402
from xsections.render.export import export  # noqa: E402
from xsections.render.pdfprefs import add_print_prefs  # noqa: E402
from xsections.render.scales import plan  # noqa: E402

PREFS = {"/PrintScaling": "/None", "/PickTrayByPDFSize": True}


def without_pypdf():
    return mock.patch.dict(sys.modules, {"pypdf": None})


@contextlib.contextmanager
def quiet_pypdf():
    """pypdf logs a warning for each repair it makes; keep the test output clean."""
    logger = logging.getLogger("pypdf")
    level = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        logger.setLevel(level)


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


def write(path, data):
    with open(path, "wb") as fh:
        fh.write(data)


def strict_prefs(path):
    """(/ViewerPreferences as a dict, catalog /Version, reader) read by pypdf in strict mode."""
    rd = PdfReader(path, strict=True)
    root = rd.trailer["/Root"].get_object()
    vp = root.get("/ViewerPreferences")
    items = vp.get_object().items() if vp is not None else []
    prefs = {str(k): (v.value if isinstance(v, BooleanObject) else str(v)) for k, v in items}
    return prefs, str(root.get("/Version")), rd


def catalog_into_object_stream(data: bytes) -> bytes:
    """`data` plus a revision that moves the catalog into a Flate object stream, indexed by a
    Flate xref stream with a PNG 'Up' predictor."""
    pdf = inc._Pdf(data)
    root = inc._ref(inc._get(pdf.trailer, b"/Root"))[0]
    size = int(inc._get(pdf.trailer, b"/Size"))
    stm, xref = size, size + 1
    head = b"%d 0 " % root
    body = zlib.compress(head + pdf.object_bytes(root))
    out = bytearray(data)
    stm_off = len(out)
    out += (b"%d 0 obj\n<< /Type /ObjStm /N 1 /First %d /Filter /FlateDecode /Length %d >>\nstream\n"
            % (stm, len(head), len(body)) + body + b"\nendstream\nendobj\n")
    xref_off = len(out)
    rows = [b"\x02" + stm.to_bytes(4, "big") + (0).to_bytes(2, "big"),         # catalog: in the ObjStm
            b"\x01" + stm_off.to_bytes(4, "big") + (0).to_bytes(2, "big"),     # the ObjStm
            b"\x01" + xref_off.to_bytes(4, "big") + (0).to_bytes(2, "big")]    # this xref stream
    encoded, prev = bytearray(), bytes(7)
    for r in rows:                                                              # PNG Up predictor
        encoded += b"\x02" + bytes((a - b) & 255 for a, b in zip(r, prev))
        prev = r
    packed = zlib.compress(bytes(encoded))
    keep = b" ".join(k + b" " + v for k, v in pdf.trailer if k in (b"/Root", b"/Info", b"/ID"))
    out += (b"%d 0 obj\n<< /Type /XRef /Size %d /Prev %d /W [1 4 2] /Index [%d 1 %d 2] %s "
            b"/Filter /FlateDecode /DecodeParms << /Columns 7 /Predictor 12 >> /Length %d >>\nstream\n"
            % (xref, xref + 1, pdf.startxref, root, stm, keep, len(packed))
            + packed + b"\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n" % xref_off)
    return bytes(out)


RAW = {}          # the exporter's PDFs before print preferences, made once per run


def setUpModule():  # noqa: N802 - unittest hook
    RAW["dir"] = tempfile.mkdtemp(prefix="xsec_pdfprefs_")
    RAW["tiled"] = os.path.join(RAW["dir"], "tiled_raw.pdf")       # 4 Tabloid tiles
    RAW["letter"] = os.path.join(RAW["dir"], "letter_raw.pdf")     # one Letter sheet
    with mock.patch("xsections.render.export.add_print_prefs", return_value=False):
        for key, model, settings in (
                ("tiled", make_model(length=4600.0), make_settings(h_scale=100.0, allowed_sheets=["tabloid"])),
                ("letter", make_model(), make_settings(allowed_sheets=["letter"]))):
            export(model, settings, plan(model, settings), RAW[key])


def tearDownModule():  # noqa: N802 - unittest hook
    shutil.rmtree(RAW["dir"], ignore_errors=True)


class FallbackCase(unittest.TestCase):
    def setUp(self):
        self.dir, self.tiled, self.letter = RAW["dir"], RAW["tiled"], RAW["letter"]

    def copy(self, src, name):
        dst = os.path.join(self.dir, name)
        shutil.copyfile(src, dst)
        return dst

    def assert_same_document(self, original, updated, pages_to_render=(1,)):
        """Same pages and MediaBoxes, and GDAL renders them pixel for pixel the same."""
        a, b = PdfReader(original, strict=True), PdfReader(updated, strict=True)
        self.assertEqual(len(b.pages), len(a.pages))
        for pa, pb in zip(a.pages, b.pages):
            self.assertEqual([float(v) for v in pb.mediabox], [float(v) for v in pa.mediabox])
        for n in pages_to_render:
            ra, _ = M.load_pdf_raster(original, 72, page=n)
            rb, _ = M.load_pdf_raster(updated, 72, page=n)
            self.assertTrue(np.array_equal(ra, rb), f"page {n} renders differently")


class IncrementalFallback(FallbackCase):
    def test_tiled_multipage(self):
        path = self.copy(self.tiled, "tiled.pdf")
        before = read(path)
        self.assertNotIn(b"/ViewerPreferences", before)
        with without_pypdf():
            self.assertTrue(add_print_prefs(path))
        after = read(path)
        self.assertTrue(after.startswith(before), "the fallback appends; it never rewrites")
        vp, version, rd = strict_prefs(path)
        self.assertEqual(vp, PREFS)
        self.assertEqual(version, "/1.7")
        self.assertEqual(len(rd.pages), 4)
        self.assert_same_document(self.tiled, path, pages_to_render=(1, 4))

    def test_export_without_pypdf(self):
        model, settings = make_model(), make_settings(allowed_sheets=["letter"])
        path = os.path.join(self.dir, "exported.pdf")
        with without_pypdf():
            self.assertEqual(export(model, settings, plan(model, settings), path), [path])
        vp, version, _ = strict_prefs(path)
        self.assertEqual((vp, version), (PREFS, "/1.7"))
        self.assertEqual(read(path).count(b"%%EOF"), 2)            # the original plus our update
        self.assert_same_document(self.letter, path)

    def test_twice(self):
        path = self.copy(self.letter, "twice.pdf")
        with without_pypdf():
            self.assertTrue(add_print_prefs(path))
            self.assertTrue(add_print_prefs(path))
        vp, version, _ = strict_prefs(path)
        self.assertEqual((vp, version), (PREFS, "/1.7"))
        self.assertEqual(inc.read_viewer_prefs(read(path)), {"/PrintScaling": "/None", "/PickTrayByPDFSize": "true"})
        self.assert_same_document(self.letter, path)

    def test_catalog_in_object_stream(self):
        src = os.path.join(self.dir, "objstm_src.pdf")
        write(src, catalog_into_object_stream(read(self.letter)))
        pdf = inc._Pdf(read(src))
        root = inc._ref(inc._get(pdf.trailer, b"/Root"))[0]
        self.assertEqual(pdf.xref[root][0], "o")                   # the catalog really is in the ObjStm
        PdfReader(src, strict=True)                                # and the source is a valid PDF
        path = self.copy(src, "objstm.pdf")
        with without_pypdf():
            self.assertTrue(add_print_prefs(path))
        after = read(path)
        self.assertTrue(after.startswith(read(src)))
        self.assertTrue(inc._Pdf(after).newest_is_stream, "an xref-stream file gets an xref-stream update")
        vp, version, _ = strict_prefs(path)
        self.assertEqual((vp, version), (PREFS, "/1.7"))
        self.assert_same_document(self.letter, path)

    def test_existing_prefs_are_kept(self):
        src = os.path.join(self.dir, "indirect_vp_src.pdf")
        w = PdfWriter(clone_from=self.letter)
        vp = DictionaryObject({NameObject("/HideToolbar"): BooleanObject(True),
                               NameObject("/PrintScaling"): NameObject("/AppDefault")})
        w.root_object[NameObject("/ViewerPreferences")] = w._add_object(vp)     # indirect, as some writers do
        w.write(src)
        path = self.copy(src, "indirect_vp.pdf")
        with without_pypdf():
            self.assertTrue(add_print_prefs(path))
        vp, _, _ = strict_prefs(path)
        self.assertEqual(vp, dict(PREFS, **{"/HideToolbar": True}))


class MalformedLeftAlone(FallbackCase):
    """A file that cannot be parsed makes add_print_prefs return False and stay byte for byte the same."""

    def bad_files(self):
        good = read(self.letter)
        start = good.rfind(b"startxref")
        return {
            "not a pdf": b"hello, world\n",
            "truncated": good[:len(good) // 2],
            "wrong startxref": good[:start] + b"startxref\n12345\n%%EOF\n",
            "no trailer": good[:good.rfind(b"trailer")],
            "empty": b"",
        }

    def test_fallback_returns_false(self):
        for name, data in self.bad_files().items():
            with self.subTest(name):
                path = os.path.join(self.dir, "bad.pdf")
                write(path, data)
                with without_pypdf():
                    self.assertFalse(add_print_prefs(path))
                self.assertEqual(read(path), data)

    def test_pypdf_never_raises(self):
        for name, data in self.bad_files().items():
            with self.subTest(name):
                path = os.path.join(self.dir, "bad.pdf")
                write(path, data)
                with quiet_pypdf():
                    written = add_print_prefs(path)
                if not written:                            # pypdf may repair some of these (then True)
                    self.assertEqual(read(path), data)
                else:
                    PdfReader(path, strict=True)

    def test_encrypted(self):
        w = PdfWriter(clone_from=self.letter)
        try:
            w.encrypt("user", "owner", algorithm="RC4-128")
        except Exception as e:                            # pragma: no cover - pypdf without RC4 support
            self.skipTest(f"pypdf cannot encrypt here: {e}")
        path = os.path.join(self.dir, "encrypted.pdf")
        w.write(path)
        data = read(path)
        with without_pypdf():
            self.assertFalse(add_print_prefs(path))
        self.assertEqual(read(path), data)
        self.assertFalse(add_print_prefs(path))
        self.assertEqual(read(path), data)

    def test_lexer_stops_at_the_end(self):
        """Unterminated objects raise PdfError instead of looping."""
        for bad in (b"[1 2", b"(abc", b"(a\\", b"<abc", b"<< /A", b"<< /A >", b"<< 1 2 >>", b"]"):
            with self.subTest(bad):
                with self.assertRaises(inc.PdfError):
                    inc._scan(bad, 0)


if __name__ == "__main__":
    unittest.main()
