"""0.3.6 stage S: the icon painter of the Other features symbol drop-down (ui/symbol_icons.py): every symbol at
22 x 16 px and at device pixel ratio 2, in its usual colour or a given one, theme-independent, drawn from the same
geometry as the sheets (render/symbols.py), resting 2 px above the bottom; a polygon row's bracket mark (build spec
2.7, tests 8.1)."""
import unittest

from tests.fixtures import start_app

APP = start_app()

from qgis.PyQt.QtCore import QSize  # noqa: E402
from qgis.PyQt.QtGui import QColor, QGuiApplication, QImage, QPalette  # noqa: E402

from xsections.render import symbols as SY  # noqa: E402
from xsections.ui import symbol_icons as I  # noqa: E402

# a pixel is ink at this alpha or more: antialiasing spills a little coverage (at most ~11 %, alpha 28) one pixel past
# an edge that lies exactly on a pixel boundary
INK_ALPHA = 64


def pixels(pm):
    """[(x, y, QColor)] of a pixmap's image, device pixels."""
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    return [(x, y, img.pixelColor(x, y)) for y in range(img.height()) for x in range(img.width())]


def ink(pm, alpha=INK_ALPHA):
    return [(x, y, c) for x, y, c in pixels(pm) if c.alpha() >= alpha]


def near(c, color, tol):
    q = QColor(color)
    return abs(c.red() - q.red()) <= tol and abs(c.green() - q.green()) <= tol and abs(c.blue() - q.blue()) <= tol


class SymbolPixmaps(unittest.TestCase):
    def test_sizes_and_device_pixel_ratio(self):
        self.assertEqual((I.ICON_W, I.ICON_H, I.ICON_S_RATIO, I.ICON_MARGIN), (22, 16, 11.0 / 16.0, 1.0))
        for key in SY.SHAPE_KEYS:
            pm = I.symbol_pixmap(key)
            self.assertEqual((pm.width(), pm.height(), pm.devicePixelRatio()), (22, 16, 1.0), key)
            pm2 = I.symbol_pixmap(key, dpr=2.0)
            self.assertEqual((pm2.width(), pm2.height(), pm2.devicePixelRatio()), (44, 32, 2.0), key)
            icon = I.symbol_icon(key)
            self.assertFalse(icon.isNull(), key)
            self.assertEqual(sorted((s.width(), s.height()) for s in icon.availableSizes()), [(22, 16), (44, 32)])
            hi = icon.pixmap(QSize(22, 16), 2.0)
            self.assertEqual((hi.width(), hi.height(), hi.devicePixelRatio()), (44, 32, 2.0), key)
        big = I.symbol_pixmap("spring", width=44, height=32)
        self.assertEqual((big.width(), big.height()), (44, 32))

    def test_usual_colour_or_the_given_one(self):
        for key in SY.SHAPE_KEYS:
            px = ink(I.symbol_pixmap(key))
            got = sum(1 for _, _, c in px if near(c, SY.usual_color(key), 40))
            self.assertGreaterEqual(got, 6, f"{key}: {got} px of {SY.usual_color(key)}")
            red = ink(I.symbol_pixmap(key, "#e00000"))
            self.assertGreaterEqual(sum(1 for _, _, c in red if near(c, "#e00000", 40)), 6, key)
            if SY.usual_color(key) != "#e00000":
                self.assertEqual([c for _, _, c in red if near(c, SY.usual_color(key), 10)
                                  and not near(c, "#ffffff", 10)], [], key)
        # an unknown key: the fallback circle
        self.assertEqual(I.symbol_pixmap("hexagon").toImage(), I.symbol_pixmap("circle").toImage())

    def test_margins_and_resting(self):
        W, H = I.ICON_W, I.ICON_H
        for key in SY.SHAPE_KEYS:
            for dpr in (1.0, 2.0):
                px = ink(I.symbol_pixmap(key, dpr=dpr))
                m = int(I.ICON_MARGIN * dpr)
                xs, ys = [x for x, _, _ in px], [y for _, y, _ in px]
                self.assertGreaterEqual(min(xs), m, key)
                self.assertLessEqual(max(xs), W * dpr - 1 - m, key)
                self.assertGreaterEqual(min(ys), m, key)
                if SY.symbol(key).rests:                 # its lowest ink row 2 px above the bottom
                    self.assertEqual(max(ys), int(round((H - 2) * dpr)) - 1, f"{key} at {dpr}x")
                else:                                    # the benchmark: centred
                    self.assertAlmostEqual((min(ys) + max(ys) + 1) / 2.0, H * dpr / 2.0, delta=0.5 * dpr)
                    self.assertAlmostEqual((min(xs) + max(xs) + 1) / 2.0, W * dpr / 2.0, delta=0.5 * dpr)

    def test_drawn_from_the_glyph_geometry(self):
        """The ink box's aspect ratio is the glyph's (glyph_bbox) within 20 % for the symbols drawn at their nominal
        size (11 px in 16; a few are shrunk to fit), measured at 2x on pixels of at least half coverage."""
        unshrunk = 0
        for key in SY.SHAPE_KEYS:
            size_pt, f, ox, oy = I.icon_place(key)
            self.assertAlmostEqual(size_pt, 11.0)
            self.assertLessEqual(f, 1.0)
            if f < 1.0:
                continue
            unshrunk += 1
            left, right, bottom, top = SY.glyph_bbox(key, size_pt, 1.0)
            px = ink(I.symbol_pixmap(key, dpr=2.0), alpha=128)
            xs, ys = [x for x, _, _ in px], [y for _, y, _ in px]
            got = (max(xs) - min(xs) + 1) / (max(ys) - min(ys) + 1)
            want = (right - left) / (top - bottom)
            self.assertLess(abs(got / want - 1.0), 0.2, f"{key}: {got:.2f} vs {want:.2f}")
        self.assertGreaterEqual(unshrunk, 24)

    def test_theme_independent(self):
        before = {key: I.symbol_pixmap(key).toImage() for key in SY.SHAPE_KEYS}
        brackets = (I.bracket_pixmap("#7a4fb0").toImage(), I.bracket_pixmap("#7a4fb0", "dash").toImage())
        old = QGuiApplication.palette()
        try:
            dark = QPalette(QColor("#202020"))
            for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
                dark.setColor(role, QColor("#f0f0f0"))
            dark.setColor(QPalette.ColorRole.Base, QColor("#101010"))
            QGuiApplication.setPalette(dark)
            for key in SY.SHAPE_KEYS:
                self.assertTrue(I.symbol_pixmap(key).toImage() == before[key], key)
            self.assertTrue(I.bracket_pixmap("#7a4fb0").toImage() == brackets[0])
            self.assertTrue(I.bracket_pixmap("#7a4fb0", "dash").toImage() == brackets[1])
        finally:
            QGuiApplication.setPalette(old)

    def test_background(self):
        img = I.symbol_pixmap("well", background="#ffffff").toImage()
        for x, y in ((0, 0), (21, 15), (0, 15), (21, 0)):
            self.assertEqual((img.pixelColor(x, y).name(), img.pixelColor(x, y).alpha()), ("#ffffff", 255))
        clear = I.symbol_pixmap("well").toImage()
        self.assertEqual(clear.pixelColor(0, 0).alpha(), 0)
        hi = I.symbol_icon("well", background="#ffffff").pixmap(QSize(22, 16), 2.0).toImage()
        self.assertEqual((hi.pixelColor(0, 0).name(), hi.pixelColor(0, 0).alpha()), ("#ffffff", 255))


class BracketMark(unittest.TestCase):
    def test_solid_and_dashed(self):
        solid, dash = I.bracket_pixmap("#7a4fb0"), I.bracket_pixmap("#7a4fb0", "dash")
        self.assertEqual((solid.width(), solid.height()), (22, 16))
        self.assertFalse(solid.toImage() == dash.toImage())
        for pm in (solid, dash):
            px = ink(pm)
            self.assertGreaterEqual(sum(1 for _, _, c in px if near(c, "#7a4fb0", 40)), 6)
            xs, ys = [x for x, _, _ in px], [y for _, y, _ in px]
            self.assertGreaterEqual(min(xs), 2)
            self.assertLessEqual(max(xs), 19)
            self.assertLessEqual(max(ys) - min(ys), 6)          # the line and its 4 px ticks
        self.assertGreater(len(ink(solid)), len(ink(dash)))       # the gaps
        hi = I.bracket_pixmap("#7a4fb0", dpr=2.0)
        self.assertEqual((hi.width(), hi.height(), hi.devicePixelRatio()), (44, 32, 2.0))
        icon = I.bracket_icon("#7a4fb0", "dash")
        self.assertEqual(sorted((s.width(), s.height()) for s in icon.availableSizes()), [(22, 16), (44, 32)])
        bg = I.bracket_pixmap("#7a4fb0", background="#ffffff").toImage()
        self.assertEqual(bg.pixelColor(0, 0).name(), "#ffffff")

    def test_a_dashed_mark_keeps_its_ticks_solid(self):
        """(fix 0.3.6) As on the sheet, only the line of a dashed mark is dashed: its ticks are the solid mark's (ink
        in the same pixels of their columns, the corners included), the line has gaps between them."""
        for dpr in (1.0, 2.0):                    # (pixels of nearly half coverage or more: the antialiasing differs
            #                                       by a hair between one polyline and a tick and a line)
            solid = {(x, y) for x, y, _ in ink(I.bracket_pixmap("#7a4fb0", dpr=dpr), alpha=100)}
            dash = {(x, y) for x, y, _ in ink(I.bracket_pixmap("#7a4fb0", "dash", dpr=dpr), alpha=100)}
            W, y = int(I.ICON_W * dpr), round(I.ICON_H / 3.0)               # the line's y (logical px)
            ticks = {x for x, yy in solid if yy > (y + 1.5) * dpr}           # the columns with ink under the line
            left, right = [x for x in ticks if x < W / 2], [x for x in ticks if x > W / 2]
            self.assertTrue(left and right, dpr)
            self.assertEqual({q for q in dash if q[0] in ticks}, {q for q in solid if q[0] in ticks}, dpr)
            row = int(y * dpr)                                              # the line's row: gaps only when dashed
            between = range(max(left) + 1, min(right))
            self.assertEqual([x for x in between if (x, row) not in solid], [], dpr)
            self.assertTrue([x for x in between if (x, row) not in dash], dpr)


if __name__ == "__main__":
    unittest.main()
