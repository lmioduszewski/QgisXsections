"""The 0.3.6 panel's visual system (DESIGN.md decision 27, stage P1: ui/widgets.py) on its own: offscreen, small
widgets, no project. The light and dark tokens (theme_for), the section tile / bar and its count chip, the open
section's body on its rail, the Flare band (paint_flare) and the layer cards' spacing (link_cards), the whole-header
click, subsections and field names, the pills, Verbose and its hints (QgsSettings only in the test profile that
fixtures.start_app sets), the row tabs, the check badge / card / host, the swatches, SurfaceRow on LayerCard and the
stylesheet."""
import os
import time
import unittest

from tests.fixtures import start_app, timing_test, wait_ms

APP = start_app()

from qgis.core import QgsSettings  # noqa: E402
from qgis.PyQt.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor, QEnterEvent, QFontMetrics, QImage, QPainter, QPalette  # noqa: E402
from qgis.PyQt.QtTest import QTest  # noqa: E402
from qgis.PyQt.QtWidgets import (QApplication, QCheckBox, QComboBox, QLabel, QToolButton, QVBoxLayout,  # noqa: E402
                                 QWidget)

from xsections.core.model import SURFACE_DEFAULTS  # noqa: E402
from xsections.ui import settings_store  # noqa: E402
from xsections.ui import widgets as W  # noqa: E402


def light_palette():
    pal = QPalette()
    R = QPalette.ColorRole
    for role, c in ((R.Window, "#efefef"), (R.WindowText, "#000000"), (R.Base, "#ffffff"), (R.Text, "#000000"),
                    (R.Button, "#efefef"), (R.ButtonText, "#000000")):
        pal.setColor(role, QColor(c))
    pal.setColor(QPalette.ColorGroup.Disabled, R.WindowText, QColor("#bebebe"))
    return pal


def night_palette():
    """QGIS's Night Mapping theme (resources/themes/Night Mapping/palette.txt)."""
    pal = QPalette()
    R, G = QPalette.ColorRole, QPalette.ColorGroup
    for role, c in ((R.Window, "#323232"), (R.WindowText, "#dddddd"), (R.Base, "#202020"),
                    (R.AlternateBase, "#2b2b2b"), (R.Text, "#dddddd"), (R.Button, "#535353"),
                    (R.ButtonText, "#dddddd"), (R.BrightText, "#ffffff"), (R.Highlight, "#d7801a"),
                    (R.HighlightedText, "#323232"), (R.ToolTipBase, "#535353"), (R.ToolTipText, "#dddddd"),
                    (R.PlaceholderText, "#8a8a8a"), (R.Light, "#3c3c3c"), (R.Mid, "#535353"), (R.Dark, "#202020"),
                    (R.Shadow, "#000000")):
        pal.setColor(role, QColor(c))
    for role in (R.WindowText, R.Text, R.ButtonText):
        pal.setColor(G.Disabled, role, QColor("#777777"))
    return pal


PALETTES = (("light", light_palette), ("dark", night_palette))

LIGHT = dict(bar="#193340", bar_hover="#21414f", bar_disabled="#9aa8b0", on_bar="#ffffff", heading="#193340",
             muted="#5a6b74", ink2="#44545d", rule="#d7dee2", field_line="#c9d2d7", chip="#e3e9ec",
             chip_ink="#4a5c65", chip_on="#dde7ed", panel2="#e9eef1", card_foot="#f4f6f8", link="#446f85",
             warn="#9a6510", warn_bg="#f6eedd", ok="#16a34a", tile="#dbe3e8", tile_hover="#cfd9df",
             tile_ink="#193340", open_body="#ffffff", row_rail="#3c86aa", row_open="#e3eff5", band_line="#8fb6ca",
             pop="#ffffff", pop_line="#e7c98f", amber="#b7791f", amber_bg="#fbf1de", count_open_ink="#ffe2a8")
DARK = dict(bar="#2f5a6f", bar_hover="#386a82", on_bar="#ffffff", heading="#a9c8d8", muted="#93a5ae",
            ink2="#b7c4ca", rule="#2d3c45", field_line="#3a4a53", chip="#26353d", chip_ink="#c3d0d6",
            chip_on="#2b4250", panel2="#213039", card_foot="#1a252c", link="#8fbad0", warn="#e6b65c",
            warn_bg="#3b2f15", ok="#4ade80", tile="#233038", tile_hover="#2b3a44", tile_ink="#d3e1e8",
            open_body="#172128", row_rail="#5aa9cf", row_open="#1c3341", band_line="#3f6a80", pop="#1b272e",
            pop_line="#6b5326", amber="#e8b45c", amber_bg="#3a2e17", count_open_ink="#ffe2a8")
RGBA = dict(chip_tile=(25, 51, 64, 26), chip_open=(255, 255, 255, 41), count_open_bg=(255, 214, 140, 56))


def settle():
    for _ in range(12):
        APP.processEvents()


def image(w):
    return w.grab().toImage()


def px(img, x, y):
    k = img.devicePixelRatio()
    return img.pixelColor(int(x * k), int(y * k))


def dist(a, b):
    a, b = QColor(a), QColor(b)
    return abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())


def blend(top, bottom):
    """`top` (translucent) over `bottom`."""
    a = top.alpha() / 255.0
    return QColor(*(round(t * a + b * (1 - a)) for t, b in ((top.red(), bottom.red()), (top.green(), bottom.green()),
                                                           (top.blue(), bottom.blue()))))


def darkest(img, x0, x1, y0=0, y1=None):
    k = img.devicePixelRatio()
    y1 = img.height() / k if y1 is None else y1
    return min((img.pixelColor(x, y) for x in range(int(x0 * k), int(x1 * k))
                for y in range(int(y0 * k), int(y1 * k))), key=lambda c: c.red() + c.green() + c.blue())


def runs(img, y, x0, x1, color, tol=60):
    """The lengths of the runs of `color` along device row `y` from x0 to x1 (device px), and of the gaps between."""
    on, off, n, gap = [], [], 0, 0
    for x in range(x0, x1):
        if dist(img.pixelColor(x, y), color) < tol:
            if gap and on:
                off.append(gap)
            gap, n = 0, n + 1
        else:
            if n:
                on.append(n)
            n, gap = 0, gap + 1
    if n:
        on.append(n)
    return on, off


class Count:
    def __init__(self, signal):
        self.args = []
        signal.connect(lambda *a: self.args.append(a))

    def __len__(self):
        return len(self.args)


def wait_until(pred, ms):
    end = time.monotonic() + ms / 1000.0
    while not pred() and time.monotonic() < end:
        QTest.qWait(10)
    return pred()


def enter(w):
    p = QPointF(2.0, 2.0)
    QApplication.sendEvent(w, QEnterEvent(p, p, QPointF(w.mapToGlobal(QPoint(2, 2)))))


def leave(w):
    QApplication.sendEvent(w, QEvent(QEvent.Type.Leave))


def host(*widgets, width=300, height=400, pal=None):
    """A shown top-level widget holding `widgets` in a column."""
    h = QWidget()
    if pal is not None:
        h.setPalette(pal)
    lay = QVBoxLayout(h)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    for w in widgets:
        lay.addWidget(w)
    lay.addStretch(1)
    h.resize(width, height)
    h.show()
    settle()
    return h


class Card(W.LayerCard):
    """A LayerCard like the panel's rows: a lead check box, a swatch, a name area; no ⋯."""

    def __init__(self, name="Explorations"):
        super().__init__()
        self.box = QCheckBox(self.header)
        self.name_area = W.ClickableArea(self.header)
        na = QVBoxLayout(self.name_area)
        na.setContentsMargins(0, 0, 0, 0)
        na.setSpacing(0)
        self.name_label = W.ElidedLabel(name, parent=self.name_area)
        self.sub_label = W.ElidedLabel("ExploName · black", small=True, parent=self.name_area)
        na.addWidget(self.name_label)
        na.addWidget(self.sub_label)
        self._place_header(self.box, W.BarSwatch(), self.name_area, None)
        self.name_area.clicked.connect(self.toggle_editor)          # as the panel's rows do
        ed = QVBoxLayout(self.editor)
        ed.addWidget(QLabel("the editor"))


def margins(card):
    m = card.card_layout.contentsMargins()
    return (m.left(), m.top(), m.right(), m.bottom())


# ================================================================ 1. tokens
class Tokens(unittest.TestCase):
    def test_light_and_dark(self):
        for name, make in PALETTES:
            pal = make()
            t = W.theme_for(pal)
            self.assertEqual(t.dark, name == "dark")
            for key, value in (LIGHT if name == "light" else DARK).items():
                self.assertEqual(getattr(t, key).name(), value, (name, key))
            for key, rgba in RGBA.items():
                self.assertEqual(getattr(t, key).getRgb(), rgba, (name, key))
            self.assertEqual(t.ink.name(), pal.color(QPalette.ColorRole.Text).name())
            self.assertEqual(t.field.name(), pal.color(QPalette.ColorRole.Base).name())
            self.assertEqual(t.disabled.name(), pal.color(QPalette.ColorGroup.Disabled,
                                                          QPalette.ColorRole.WindowText).name())
        dark = W.theme_for(night_palette())
        self.assertEqual(dark.bar_disabled.name(), W._mix(QColor("#2f5a6f"), QColor("#323232"), 0.55).name())
        self.assertNotEqual(dark.bar.name(), "#d7801a")          # no longer the palette's orange highlight
        self.assertGreater(dark.muted.lightness() - QColor("#323232").lightness(), 70)

    def test_ink_and_field_follow_the_palette_and_the_cache(self):
        pal = light_palette()
        pal.setColor(QPalette.ColorRole.Text, QColor("#102030"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#fafaf0"))
        t = W.theme_for(pal)
        self.assertEqual((t.ink.name(), t.field.name()), ("#102030", "#fafaf0"))
        self.assertIs(W.theme_for(QPalette(pal)), t)                # one Theme per palette
        self.assertIsNot(W.theme_for(light_palette()), t)


# ================================================================ 2.-3. sections
class Sections(unittest.TestCase):
    def test_tile_and_bar(self):
        for name, make in PALETTES:
            pal = make()
            t = W.theme_for(pal)
            h = W.SectionHeader("Line", "line")
            h.setPalette(pal)
            h.resize(300, W.SECTION_H)
            self.assertEqual((W.SectionHeader.HEIGHT, h.height()), (30, 30))
            img = image(h)
            self.assertLess(dist(px(img, 150, 15), t.tile), 8, name)
            self.assertGreater(dist(px(img, 0, 0), t.tile), 8, name)            # a rounded tile
            h.setOpen(True)
            img = image(h)
            self.assertLess(dist(px(img, 150, 15), t.bar), 8, name)
            self.assertLess(dist(px(img, 0, 29), t.bar), 8, name)               # square bottom corners
            self.assertGreater(dist(px(img, 0, 0), t.bar), 8, name)             # rounded top ones

    def test_count_chip(self):
        for name, make in PALETTES:
            pal = make()
            t = W.theme_for(pal)
            h = W.SectionHeader("Explorations", "explorations")
            h.setPalette(pal)
            h.resize(300, W.SECTION_H)
            h.setChip("3 layers · 12 plotted")
            self.assertIsNone(h.parts()["count"])
            h.setProblems(2, "2 layers need a look")
            self.assertEqual(h.problems(), 2)
            self.assertIn("2 layers need a look", h.toolTip())
            self.assertIn("3 layers · 12 plotted", h.toolTip())
            parts = h.parts()
            count, chip = parts["count"], parts["chip"]
            self.assertGreater(count.left(), chip.right())                     # right of the main chip
            self.assertLessEqual(count.right(), 300 - 9)
            x, y = count.right() - 2.5, count.center().y()
            self.assertLess(dist(px(image(h), x, y), t.amber_bg), 8, name)
            h.setOpen(True)
            self.assertLess(dist(px(image(h), x, y), blend(t.count_open_bg, t.bar)), 12, name)
            h.setProblems(0)
            self.assertIsNone(h.parts()["count"])
            self.assertEqual(h.toolTip(), "3 layers · 12 plotted")

    def test_titles_never_elided(self):
        for width in (340, 326):
            for title in ("Line", "Surfaces", "Explorations", "Other features", "Scale & sheet", "Sheet style"):
                h = W.SectionHeader(title, "other")
                h.resize(width, W.SECTION_H)
                h.setChip("3 of 3 on · 46 plotted")
                h.setProblems(3)
                parts = h.parts()
                self.assertEqual(parts["title"], title.upper(), (width, title))
                self.assertIsNotNone(parts["chip"], (width, title))

    def test_body(self):
        for name, make in PALETTES:
            pal = make()
            t = W.theme_for(pal)
            b = W.SectionBody()
            b.setPalette(pal)
            b.resize(300, 200)
            self.assertEqual(b.objectName(), "xsSectionBody")
            m = b.body_layout.contentsMargins()
            self.assertEqual((m.left(), m.top(), m.right(), m.bottom(), b.body_layout.spacing()),
                             (13, 10, 11, 13, 8))
            img = image(b)
            self.assertLess(dist(px(img, 1, 100), t.bar), 8, name)              # the rail
            self.assertLess(dist(px(img, 150, 100), t.open_body), 8, name)
            self.assertLess(dist(px(img, 299, 100), t.bar), 8, name)            # 1 px right border
            self.assertLess(dist(px(img, 150, 199), t.bar), 8, name)            # and bottom border
            self.assertLess(dist(px(img, 150, 0), t.open_body), 8, name)        # no top border: the bar is above

    def test_collapsible_section(self):
        sec = W.CollapsibleSection("Explorations", "explorations", "xsTestGroup")
        self.assertIsInstance(sec.body, W.SectionBody)
        self.assertIs(sec.body_layout, sec.body.body_layout)
        self.assertTrue(sec.isCollapsed())
        self.assertEqual(sec.layout().contentsMargins().bottom(), 3)
        ch = Count(sec.collapsedStateChanged)
        sec.setCollapsed(False)
        self.assertEqual((sec.layout().contentsMargins().bottom(), len(ch)), (10, 1))
        self.assertTrue(sec.header.isOpen())
        sec.toggle()
        self.assertEqual(sec.layout().contentsMargins().bottom(), 3)
        first = sec.add_subsection("Layers")
        second = sec.add_subsection("All layers", [W.link_button("Show all")])
        self.assertEqual([s.title() for s in sec.findChildren(W.Subsection)], ["Layers", "All layers"])
        self.assertEqual((first.body_layout.contentsMargins().top(), second.body_layout.contentsMargins().top()),
                         (0, 12))
        sec.setProblems(1, "1 layer needs a look")
        self.assertEqual((sec.problems(), sec.header.problems()), (1, 1))
        sec.setChip("Ground + 1", warn=True)
        self.assertEqual((sec.chipText(), sec.chipWarn()), ("Ground + 1", True))

    def test_icons(self):
        self.assertEqual(sorted(W.ICONS), ["explorations", "line", "other", "scale", "style", "surfaces"])
        self.assertIn('viewBox="0 0 14 14"', W._SVG_HEAD)
        self.assertNotIn("stroke=", W._SVG_HEAD)
        self.assertIn('<circle cx="3.5" cy="3.5" r="2" fill="currentColor"/>', W.ICONS["other"])
        for key in W.ICONS:
            self.assertIsNotNone(W._icon_renderer(key, "#193340"), key)


# ================================================================ 4.-6. the Flare and the layer cards
class Flare(unittest.TestCase):
    def test_paint_flare(self):
        for name, make in PALETTES:
            t = W.theme_for(make())
            img = QImage(300, 200, QImage.Format.Format_ARGB32)
            img.fill(t.open_body)
            p = QPainter(img)
            W.paint_flare(p, t, 4, 40, 120, 280, 70)
            p.end()

            def c(x, y):
                return img.pixelColor(x, y)
            self.assertLess(dist(c(100, 80), t.row_open), 6, name)
            self.assertLess(dist(c(2, 80), t.row_rail), 6, name)                # the rail beside the band
            self.assertLess(dist(c(2, 39), t.row_rail), dist(c(2, 39), t.bar), name)   # fading in above
            self.assertLess(dist(c(2, 32), t.bar), dist(c(2, 32), t.row_rail), name)
            self.assertLess(dist(c(5, 39), t.row_open), 12, name)               # the swoop
            self.assertLess(dist(c(11, 33), t.open_body), 6, name)              # inside its circle
            self.assertLess(dist(c(150, 70), t.field_line), 6, name)            # the tabs' rule
            self.assertLess(dist(c(150, 40), t.band_line), 12, name)            # the outline: top
            self.assertLess(dist(c(279, 80), t.band_line), 12, name)            # and right edge
            self.assertLess(dist(c(281, 80), t.open_body), 6, name)             # nothing right of R
            fade = c(2, 125)
            self.assertGreater(dist(fade, t.row_rail), 6, name)                 # fading back below
            self.assertGreater(dist(fade, t.bar), 6, name)

    def test_card_margins_and_link_cards(self):
        a = Card()
        self.assertEqual(margins(a), (0, 0, 0, 0))
        self.assertEqual(a.band_rect(), a.rect())
        a.set_editor_open(True)
        self.assertEqual(margins(a), (0, 8, 0, 8))                             # in the middle of a list
        a.set_first(True)
        self.assertEqual(margins(a), (0, 4, 0, 8))
        a.set_first(False)
        a.set_after_open(True)
        self.assertEqual(margins(a), (0, 0, 0, 8))
        a.set_after_open(False)
        a.set_last(True)
        self.assertEqual(margins(a), (0, 8, 0, 0))
        a.resize(300, 120)
        self.assertEqual(a.band_rect(), a.rect().adjusted(0, 8, 0, 0))
        cards = [Card(), Card(), Card()]
        cards[0].set_editor_open(True)
        cards[1].set_editor_open(True)
        W.link_cards(cards)
        self.assertEqual([margins(c) for c in cards], [(0, 4, 0, 8), (0, 0, 0, 8), (0, 0, 0, 0)])
        cards[2].set_editor_open(True)                                      # last, under an open card
        self.assertEqual(margins(cards[2]), (0, 0, 0, 0))
        cards[1].set_editor_open(False)
        W.link_cards(cards)
        self.assertEqual([margins(c) for c in cards], [(0, 4, 0, 8), (0, 0, 0, 0), (0, 8, 0, 0)])

    def test_a_card_without_a_check_box_keeps_its_columns(self):
        """(fix 0.3.6) A card with no check box (the Ground row) and no ⋯ keeps their columns, spacing included: its
        name lines up with the other cards' names, and ends where theirs do (an empty spacer got no grid spacing)."""
        full, bare = W.LayerCard(), W.LayerCard()
        box = QCheckBox(full.header)
        box.setFixedWidth(W.LayerCard.LEAD_W)
        menu = QToolButton(full.header)
        menu.setFixedSize(W.LayerCard.MENU_W, 20)
        names = []
        for card, lead, tail in ((full, box, menu), (bare, None, None)):
            area = W.ClickableArea(card.header)
            QVBoxLayout(area).addWidget(W.ElidedLabel("Ground", parent=area))
            card._place_header(lead, W.BarSwatch("#111111", card.header), area, tail)
            names.append(area)
        h = host(full, bare)
        try:
            self.assertEqual([a.x() for a in names], [names[0].x()] * 2)
            self.assertEqual([a.geometry().right() for a in names], [names[0].geometry().right()] * 2)
            self.assertEqual(names[0].x(), 7 + W.LayerCard.LEAD_W + 6 + 22 + 6)       # margin, lead, icon
        finally:
            h.close()

    def test_card_clicks_and_signal(self):
        card = Card()
        h = host(card)
        try:
            tg = Count(card.editorToggled)
            empty = QPoint(card.header.width() - 10, card.header.height() // 2)
            self.assertIs(card.header.childAt(empty), None)
            QTest.mouseClick(card.header, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, empty)
            self.assertTrue(card.editor_open())
            QTest.mouseClick(card.box, Qt.MouseButton.LeftButton)              # the check box keeps its click
            self.assertTrue(card.editor_open())
            self.assertTrue(card.box.isChecked())
            QTest.mouseClick(card.name_area, Qt.MouseButton.LeftButton)        # one toggle, not two
            self.assertFalse(card.editor_open())
            card.name_area.clicked.emit()
            card.set_editor_open(True)                                         # no change: no signal
            self.assertEqual([a[0] for a in tg.args], [True, False, True])
            self.assertEqual(card.name_label.font().weight(), W.QFont.Weight.DemiBold)  # bold while open
            card.set_editor_open(False)
            self.assertEqual(card.name_label.font().weight(), W.QFont.Weight.Normal)
        finally:
            h.close()

    def test_card_paints_only_while_closed(self):
        pal = light_palette()
        t = W.theme_for(pal)
        card = Card()
        h = host(card, pal=pal)
        try:
            leave(card)
            gap = QPoint(card.width() - 4, card.header.height() // 2)          # a point no child covers
            img = image(card)
            self.assertLess(dist(px(img, 0, card.height() // 2), t.field_line), 12)    # its border
            self.assertLess(dist(px(img, gap.x(), gap.y()), t.field), 6)               # its fill
            enter(card)
            self.assertLess(dist(px(image(card), 0, card.height() // 2), t.row_rail), 12)   # hovered
            leave(card)
            card.set_editor_open(True)
            settle()
            img = image(card)
            gap = QPoint(card.width() - 4, card.gaps()[0] + card.header.height() // 2)
            self.assertLess(dist(px(img, gap.x(), gap.y()), pal.color(QPalette.ColorRole.Window)), 6)
            self.assertLess(dist(px(img, 0, card.height() // 2), pal.color(QPalette.ColorRole.Window)), 6)
        finally:
            h.close()

    def test_checks(self):
        card = Card()
        h = host(card)
        try:
            ch = Count(card.checksChanged)
            self.assertFalse(card.has_check() or not card.badge.isHidden())
            card.set_check([W.Problem("a", W.CardInfo("t"), 2), W.Problem("b", W.CardInfo("u"))])
            self.assertTrue(card.has_check())
            self.assertFalse(card.badge.isHidden())
            self.assertEqual(card.badge.text(), "3")
            self.assertEqual(card.check_text(), "a · +1 more")
            self.assertEqual(card.problem_label.text(), "a · +1 more")
            self.assertEqual(card.problem_label.toolTip(), "a\nb")
            self.assertFalse(card.problem_label.isHidden())
            self.assertTrue(card.problem_label.isAmber())
            self.assertEqual([b.title for b in card.badge.blocks], ["t", "u"])
            self.assertEqual(len(ch), 1)
            card.set_check([W.Problem("a", W.CardInfo("t"), 2), W.Problem("b", W.CardInfo("u"))])
            self.assertEqual(len(ch), 1)                                       # nothing changed
            g = W.CardInfo("Fields were guessed", actions=[("open_depths", "Open Depths"),
                                                           ("looks_right", "Looks right")])
            card.set_check(guess=g)
            self.assertEqual((card.badge.text(), card.check_text(), card.problem_label.isHidden(), len(ch)),
                             ("check", "", True, 2))
            self.assertEqual(card.badge.actions, [("open_depths", "Open Depths"), ("looks_right", "Looks right")])
            card.set_check([W.Problem("a", W.CardInfo("t", actions=[("open_water", "Open Water"),
                                                                    ("looks_right", "Looks right")]))], g)
            self.assertEqual(card.badge.text(), "1")
            self.assertEqual(card.badge.actions, [("open_water", "Open Water"), ("looks_right", "Looks right"),
                                                  ("open_depths", "Open Depths")])   # each key once
            card.set_check()
            self.assertEqual((card.has_check(), card.badge.isHidden(), card.check_text(), len(ch)),
                             (False, True, "", 4))
        finally:
            h.close()

    def test_body_paints_the_bands(self):
        for name, make in PALETTES:
            pal = make()
            t = W.theme_for(pal)
            body = W.SectionBody()
            body.setPalette(pal)
            card = Card()
            body.body_layout.addWidget(card)
            body.body_layout.addStretch(1)
            body.watch(card)
            body.resize(300, 300)
            body.show()
            try:
                card.set_editor_open(True)
                settle()
                g = card.geometry()
                top, bottom = card.gaps()
                self.assertEqual(body.bands(), [(g.top() + top, g.bottom() + 1 - bottom, g.right() + 1, None)])
                img = image(body)
                y = g.top() + top + 10
                self.assertLess(dist(px(img, 6, y), t.row_open), 8, name)        # the 9 px left of the card
                self.assertLess(dist(px(img, g.right() - 2, y + 20), t.row_open), 8, name)
                self.assertLess(dist(px(img, g.right() + 4, y), t.open_body), 8, name)
                self.assertLess(dist(px(img, 2, y), t.row_rail), 8, name)        # the rail beside it
                self.assertLess(dist(px(img, 2, g.bottom() + 30), t.bar), 8, name)
                calls = []
                update = body.update
                body.update = lambda *a: (calls.append(1), update(*a))
                above = QWidget()
                above.setFixedHeight(30)
                body.body_layout.insertWidget(0, above)                       # the card moves down
                settle()
                self.assertTrue(calls)
                self.assertEqual(body.bands()[0][0], g.top() + top + 30 + body.body_layout.spacing())
                card.set_editor_open(False)
                self.assertEqual(body.bands(), [])
                body.unwatch(card)
                card.set_editor_open(True)
                self.assertEqual(body.bands(), [])
            finally:
                body.close()


# ================================================================ 7.-8. subsections, field names, pills
class Pieces(unittest.TestCase):
    def test_subsection_heading(self):
        for name, make in PALETTES:
            pal = make()
            t = W.theme_for(pal)
            link = W.link_button("Show all")
            sub = W.Subsection("Plotted", [link])
            h = host(sub, pal=pal)
            try:
                head = sub.heading
                self.assertIsInstance(head, W.SubsectionHeading)
                self.assertEqual((head.title(), head.height(), sub.title()), ("Plotted", W.SUBHEAD_H, "Plotted"))
                img = image(head)
                self.assertLess(dist(px(img, 3, 8), t.heading), 12, name)          # the square marker
                rule = head.rule.geometry()
                self.assertLess(dist(px(img, rule.center().x(), (W.SUBHEAD_H - 1) // 2), t.rule), 8, name)
                self.assertLess(dist(px(img, rule.center().x(), 2), pal.color(QPalette.ColorRole.Window)), 6,
                                name)                                                # never filled
                self.assertEqual(link.geometry().right(), head.width() - 1)         # the link at the right
                self.assertEqual(sub.body_layout.contentsMargins().top(), 12)
                sub.set_first(True)
                self.assertEqual(sub.body_layout.contentsMargins().top(), 0)
                self.assertIs(sub.addWidget(QLabel("x")).parentWidget(), sub)
            finally:
                h.close()

    def test_field_names(self):
        lab = W.field_label("Legend")
        self.assertEqual((lab.text(), lab.objectName(), lab.toolTip()), ("Legend", "xsFieldLabel", "Legend"))
        self.assertLess(lab.font().pointSizeF(), QApplication.font().pointSizeF())
        self.assertEqual(lab.font().weight(), W.MEDIUM)
        self.assertEqual(lab.font().letterSpacing(), 0.0)
        box = W.field_box("Drawn in", W.SegmentedControl([("Black", "black"), ("Gray", "gray")]), tip="T")
        head = next(x for x in box.findChildren(QLabel) if x.objectName() == "xsFieldLabel")
        self.assertEqual((head.text(), head.toolTip()), ("Drawn in", "T"))
        row = W.check_row(QCheckBox("Depth line"), QCheckBox("TD label"))
        self.assertEqual(row.layout().spacing(), 16)
        add = W.add_button("+ Add layer", "Add a point layer")
        self.assertEqual((add.objectName(), add.text(), add.toolTip(), add.height()),
                         ("xsAdd", "+ Add layer", "Add a point layer", 24))
        self.assertEqual(add.sizePolicy().horizontalPolicy(), W.QSizePolicy.Policy.Expanding)

    def test_pills(self):
        for name, make in PALETTES:
            pal = make()
            t = W.theme_for(pal)
            d = W.Disclosure("Units & datum")
            d.addWidget(QLabel("Ground units"))
            h = host(d, pal=pal)
            try:
                self.assertLess(d.button.sizeHint().width(), 200)
                self.assertEqual(d.button.width(), d.button.sizeHint().width())     # as wide as its text
                self.assertTrue(d.body.isHidden())
                self.assertFalse(d.isExpanded())
                x, y = d.button.width() - 5, W._DisclosureButton.H // 2
                self.assertLess(dist(px(image(d.button), x, y), t.field), 8, name)
                tg = Count(d.toggled)
                d.setExpanded(True)
                settle()
                self.assertFalse(d.body.isHidden())
                self.assertEqual(d.body.y() - d.button.geometry().bottom() - 1, 5)
                self.assertEqual(d.body.objectName(), "xsMoreBody")
                m = d.body_layout.contentsMargins()
                self.assertEqual((m.left(), m.top(), m.right(), m.bottom()), (10, 9, 10, 9))
                self.assertLess(dist(px(image(d.button), x, y), t.row_open), 8, name)
                self.assertEqual(tg.args, [(True,)])
                d.setText("Distances & printers")
                self.assertEqual(d.text(), "Distances & printers")
            finally:
                h.close()


    def test_dashed_boxes(self):
        """(fix 0.3.6) The pill's box and "+ Add layer" are dashed as the mockup's 1 px CSS border: dashes 3 px on,
        2 px off (a stylesheet's dashed border came out a hairline of 1 px dots); on hover the add button's border is
        solid, in the link colour. Their 1 px border stays in the stylesheet (transparent), so nothing moves."""
        old = QPalette(APP.palette())
        self.addCleanup(APP.setPalette, old)
        for name, make in PALETTES:
            pal = make()
            t = W.theme_for(pal)
            APP.setPalette(pal)                 # (as QGIS does; a stylesheet drops a palette set on a parent widget)
            d = W.Disclosure("Units & datum")
            d.addWidget(QLabel("Ground units"))
            add = W.add_button("+ Add layer")
            h = host(d, add)
            h.setStyleSheet(W.panel_stylesheet(t))
            try:
                d.setExpanded(True)
                settle()
                self.assertEqual(d.body.contentsRect(), d.body.rect().adjusted(1, 1, -1, -1))     # (the 1 px border)
                for w, color in ((d.body, t.row_rail), (add, t.field_line)):
                    img = image(w)
                    k = int(img.devicePixelRatio())
                    for y in (0, img.height() - 1):                                 # the top and bottom edges
                        on, off = runs(img, y, 8 * k, img.width() - 8 * k, color)
                        self.assertGreater(len(on), 5, (name, w.objectName()))
                        self.assertEqual(max(on[1:-1]), 3 * k, (name, w.objectName(), on))
                        self.assertEqual(max(off), 2 * k, (name, w.objectName(), off))
                add.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)            # hovered
                img = image(add)
                on, off = runs(img, 0, 8, img.width() - 8, t.link)
                self.assertEqual((len(on), off), (1, []), name)                      # solid
            finally:
                add.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                h.close()

    def test_pairs_stack_where_a_column_is_too_narrow(self):
        """(fix 0.3.6) pair() puts its two fields one over the other while a column would cut what it holds
        (segmented texts, spin box numbers: the 260 px dock), and side by side again when there is room; checked again
        when a number is typed and when a field appears in a column."""
        seg = W.SegmentedControl([("Off", "off"), ("Below", "below"), ("Both", "both")])
        a = W.field_box("Fill sheet", seg)
        lo, hi = W._spin(0.001, 1.0e7, 2, 10.0), W._spin(0.001, 1.0e7, 2, 1.0)
        lo.setValue(1000.0)
        hi.setValue(100.0)
        b = W.field_box("Horizontal, ft", W.hrow(lo, "/", hi, spacing=4))
        p = W.pair(a, b)
        alone = W.pair(W.field_box("Printer edge", W.SegmentedControl([("0.5 in", 0.5), ("0.3 in", 0.3)])), None,
                       (5, 4))
        h = host(p, alone, width=420)

        def check(width):
            h.resize(width, 400)
            settle()
            col = (p.width() - 8) / 2
            need = max(W._needed_width(a), W._needed_width(b))
            self.assertEqual(p.stacked(), need > col, width)
            if p.stacked():
                self.assertGreater(b.y(), a.geometry().bottom(), width)              # one over the other
                self.assertEqual((a.width(), b.width()), (p.width(), p.width()), width)
            else:
                self.assertEqual(a.geometry().bottom(), b.geometry().bottom(), width)  # side by side
                self.assertGreater(b.x(), a.geometry().right(), width)
            for x in seg.buttons():                                                   # nothing cut
                self.assertGreaterEqual(x.width(), x.fontMetrics().horizontalAdvance(x.text()) + 5, (width, x.text()))
            for s in (lo, hi):
                self.assertGreaterEqual(s.width(), W._spin_needed(s), (width, s.text()))
        try:
            self.assertEqual(seg.neededWidth(), 3 * (seg.buttons()[0].fontMetrics().horizontalAdvance("Below") + 6))
            for width in (420, 340, 300, 260, 220, 180):
                check(width)
            # the narrowest width where they sit side by side: a longer number stacks them, without a resize
            fit = 2 * W._needed_width(b) + 8 + 2
            h.resize(fit, 400)
            settle()
            self.assertFalse(p.stacked())
            lo.setValue(1234567.25)
            settle()
            self.assertTrue(p.stacked())
            self.assertGreaterEqual(lo.width(), W._spin_needed(lo))
            lo.setValue(1000.0)
            settle()
            self.assertFalse(p.stacked())
            # pair(field, None): its empty column goes while stacked, the field takes the whole width
            need = W._needed_width(alone.layout().itemAt(0).widget())
            h.resize(int(need * 9 / 5) + 8 - 3, 400)                                 # its 5 / 9 column too narrow
            settle()
            self.assertTrue(alone.stacked())
            self.assertEqual(alone.layout().itemAt(0).widget().width(), alone.width())
            self.assertTrue(alone.layout().itemAt(1).widget().isHidden())
            h.resize(420, 400)
            settle()
            self.assertFalse(alone.stacked() or alone.layout().itemAt(1).widget().isHidden())
        finally:
            h.close()
        # a field shown later in a column ("Where empty" under Field) is measured too
        where = W.SegmentedControl([("Line", "line"), ("LIDAR", "lidar"), ("Off", "off")])
        right = QWidget()
        col = QVBoxLayout(right)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(W.field_box("Field", QComboBox()))
        box = W.field_box("Where empty", where)
        col.addWidget(box)
        box.hide()
        p2 = W.pair(W.field_box("Legend", QLabel("Seeps")), right)
        h = host(p2, width=2 * where.neededWidth() - 20)
        try:
            self.assertFalse(p2.stacked())
            box.show()
            settle()
            self.assertTrue(p2.stacked())
            self.assertGreaterEqual(min(x.width() for x in where.buttons()),
                                    where.buttons()[1].fontMetrics().horizontalAdvance("LIDAR") + 5)
        finally:
            h.close()

    def test_check_boxes_in_one_column_where_two_would_cut_them(self):
        """(fix 0.3.6) checkbox_grid's two columns become one while a column is narrower than the widest box's text
        (Sheet style › Page at the 260 px dock); every text whole at any width."""
        boxes = [QCheckBox(x) for x in ("Compact layout", "Notes", "Bend lines", "Shade below ground")]
        g = W.checkbox_grid(boxes)
        h = host(g, width=420)
        need = max(x.sizeHint().width() for x in boxes)
        try:
            for width in (420, 2 * need + 8, 2 * need + 7, 220, 160):
                h.resize(width, 300)
                settle()
                two = need <= (g.width() - 8) / 2
                self.assertEqual(g.columns(), 2 if two else 1, width)
                if two:
                    self.assertEqual((boxes[1].y(), boxes[2].x()), (boxes[0].y(), boxes[0].x()), width)
                    self.assertGreater(boxes[1].x(), boxes[0].geometry().right(), width)
                else:
                    self.assertEqual({x.x() for x in boxes}, {boxes[0].x()}, width)
                    self.assertEqual(sorted(boxes, key=lambda x: x.y()), boxes, width)
                for x in boxes:
                    self.assertGreaterEqual(x.width(), min(x.sizeHint().width(), g.width()), (width, x.text()))
        finally:
            h.close()


# ================================================================ 9. Verbose
class Verbose(unittest.TestCase):
    def setUp(self):
        # the throwaway profile of fixtures.start_app (never his own)
        self.assertIn("xsec_profile_", os.environ.get("QGIS_CUSTOM_CONFIG_PATH", ""))
        self.assertTrue(os.path.normcase(QgsSettings().fileName()).startswith(
            os.path.normcase(os.environ["QGIS_CUSTOM_CONFIG_PATH"])), QgsSettings().fileName())
        QgsSettings().remove(settings_store.USER_PREFIX + W.VERBOSE_KEY)
        W.verbose_hub().reload()
        self.addCleanup(W.set_verbose, False)

    def test_off_by_default_and_stored_per_user(self):
        self.assertFalse(W.verbose())
        ch = Count(W.verbose_hub().changed)
        W.set_verbose(True)
        self.assertTrue(W.verbose())
        self.assertEqual(settings_store.user_value("verbose"), "1")
        self.assertEqual(ch.args, [(True,)])
        W.set_verbose(True)
        self.assertEqual(len(ch), 1)                                       # no change, no signal
        W.set_verbose(False)
        self.assertEqual((settings_store.user_value("verbose"), ch.args), ("0", [(True,), (False,)]))
        settings_store.set_user_value("verbose", "1")                      # (another dock)
        W.verbose_hub().reload()
        self.assertTrue(W.verbose())
        self.assertEqual(len(ch), 3)

    def test_hints(self):
        hint = W.Hint("Untick one to leave it off this section only.")
        warn = W.Hint("Guessed from the field names (check them): <b>ExploElev</b>", warn=True)
        ro = W.Readout("Plotted 3 of 4")
        h = host(hint, warn, ro)
        try:
            self.assertEqual((hint.objectName(), warn.property("warn"), ro.objectName()),
                             ("xsHint", "true", "xsReadout"))
            self.assertTrue(hint.wordWrap())
            self.assertTrue(hint.wanted())
            self.assertTrue(hint.isHidden() and warn.isHidden() and ro.isHidden())     # Verbose off
            W.set_verbose(True)
            self.assertFalse(hint.isHidden() or warn.isHidden() or ro.isHidden())
            hint.setWanted(False)
            self.assertTrue(hint.isHidden())
            hint.setWanted(True)
            self.assertFalse(hint.isHidden())
            W.set_verbose(False)
            self.assertTrue(hint.isHidden() and ro.isHidden())
            hint.setWanted(False)
            W.set_verbose(True)
            self.assertTrue(hint.isHidden())                               # nothing to say
            # the text as given; the <b> run in ink2 (the mockup's .hint b)
            self.assertEqual(warn.text(), "Guessed from the field names (check them): <b>ExploElev</b>")
            self.assertIn(W.theme_for(warn.palette()).ink2.name(), QLabel.text(warn))
            self.assertTrue(ro.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse)
            self.assertLess(ro.font().pointSizeF(), hint.font().pointSizeF())
        finally:
            h.close()

    def test_deleted_hints_leave_no_connection_behind(self):
        """(fix 0.3.6) The hub lives for the whole session: a deleted Hint (a row removed, a project loaded again)
        must leave no connection on it; a live one still follows Verbose."""
        hub = W.verbose_hub()
        before = hub.receivers(hub.changed)
        box = QWidget()
        lay = QVBoxLayout(box)
        hints = [W.Hint(f"hint {i}") for i in range(5)] + [W.Readout("plotted")]
        for x in hints:
            lay.addWidget(x)
        self.assertEqual(hub.receivers(hub.changed), before + 6)
        box.show()
        settle()
        W.set_verbose(True)
        self.assertFalse(any(x.isHidden() for x in hints))
        W.set_verbose(False)
        self.assertTrue(all(x.isHidden() for x in hints))
        box.deleteLater()
        del hints, lay
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        settle()
        self.assertEqual(hub.receivers(hub.changed), before)
        W.set_verbose(True)                                                  # (no error from a dead receiver)
        W.set_verbose(False)

    def test_a_hint_made_with_verbose_on_is_never_a_window(self):
        W.set_verbose(True)
        loose = W.Hint("top drawn first")
        loose.setHead(True)
        settle()
        self.assertFalse(loose.isVisible())
        self.assertEqual(loose.property("head"), "true")
        h = host(loose)
        try:
            self.assertTrue(loose.isVisible())
            off = W.Hint("x")
            off.setWanted(False)
            h.layout().addWidget(off)
            settle()
            self.assertTrue(off.isHidden())
        finally:
            h.close()


# ================================================================ 10. row tabs
class Tabs(unittest.TestCase):
    def test_row_tabs(self):
        pal = light_palette()
        tabs = W.RowTabs()
        self.assertEqual([tabs.addTab(t) for t in ("Layer", "Depths", "Water")], [0, 1, 2])
        h = host(tabs, pal=pal)
        try:
            self.assertEqual((tabs.count(), tabs.currentIndex(), tabs.height()), (3, 0, W.TAB_H))
            self.assertEqual([tabs.tabText(i) for i in range(3)], ["Layer", "Depths", "Water"])
            self.assertEqual(tabs.tabRect(0).x(), 7)                          # under the row's check box
            self.assertEqual([c.accessibleName() for c in tabs.findChildren(W._Tab)], ["Layer", "Depths", "Water"])
            ch = Count(tabs.currentChanged)
            QTest.mouseClick(tabs, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             tabs.tabRect(1).center())
            self.assertEqual((tabs.currentIndex(), ch.args), (1, [(1,)]))
            QTest.mouseClick(tabs, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             tabs.tabRect(1).center())
            self.assertEqual(len(ch), 1)                                       # the current one: nothing
            tabs.setCurrentIndex(0)
            settle()
            tabs.setTabDimmed(2, True, "No water-level or screen fields")
            self.assertTrue(tabs.isTabDimmed(2))
            self.assertEqual(tabs.tabToolTip(2), "No water-level or screen fields")
            img = image(tabs)
            r1, r2 = tabs.tabRect(1), tabs.tabRect(2)
            d1 = darkest(img, r1.left(), r1.right(), 0, W.TAB_H - 3)
            d2 = darkest(img, r2.left(), r2.right(), 0, W.TAB_H - 3)
            self.assertGreater(d2.lightness(), d1.lightness() + 15)             # dimmed: lighter
            t = W.theme_for(pal)
            self.assertLess(dist(px(img, tabs.tabRect(0).center().x(), W.TAB_H - 1), t.link), 8)   # underline
            self.assertLess(dist(px(img, tabs.width() - 3, W.TAB_H - 1), t.field_line), 8)        # the rule
            QTest.mouseClick(tabs, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r2.center())
            self.assertEqual(tabs.currentIndex(), 2)                           # still clickable
            tabs.setTabDimmed(2, False)
            self.assertEqual((tabs.isTabDimmed(2), tabs.tabToolTip(2)), (False, ""))
            tabs.setCurrentIndex(0)
            tabs.setFocus()
            QTest.keyClick(tabs, Qt.Key.Key_Right)
            self.assertEqual(tabs.currentIndex(), 1)
            QTest.keyClick(tabs, Qt.Key.Key_Left)
            QTest.keyClick(tabs, Qt.Key.Key_Left)
            self.assertEqual(tabs.currentIndex(), 0)
        finally:
            h.close()


# ================================================================ 11.-12. the check badge, card and host
def guess_card():
    return W.CardInfo("Fields were guessed", "Supply wells · from the field names",
                      items=[("Label", "AESI_MapLabel", ""), ("ATD level", "GW_Elev_ATD", " · elevations")],
                      actions=[("open_depths", "Open Depths"), ("looks_right", "Looks right")])


def table_card():
    return W.CardInfo("3 water levels left out", "Explorations by others · table Boring Summary, field DTW",
                      items=[("B-4", '"dry"', ""), ("MW-2", '"n/a"', "")], more=3,
                      note="Only plain numbers are read; 1,234.5 is fine.", actions=[("open_water", "Open Water")])


@timing_test
class Cards(unittest.TestCase):
    def panel(self, width=340, height=600):
        panel = QWidget()
        panel.resize(width, height)
        panel._xs_card_host = W.CardHost(panel)
        self.addCleanup(panel.close)
        return panel, panel._xs_card_host

    def badge(self, panel, x, y, blocks=None):
        b = W.CheckBadge(panel)
        b.set_check_text("check")
        b.blocks = blocks if blocks is not None else [guess_card()]
        b.actions = W.card_actions(b.blocks)
        b.resize(b.sizeHint())
        b.move(x, y)
        return b

    def test_click_opens_hover_never(self):
        panel, hst = self.panel()
        b = self.badge(panel, 290, 100)
        panel.show()
        settle()
        self.assertIs(W.find_card_host(b), hst)
        self.assertEqual((b.height(), b.toolTip()), (W.BADGE_H, "Show what to check"))
        enter(b)
        settle()
        self.assertTrue(hst.card.isHidden())                                  # hover never opens
        QTest.mouseClick(b, Qt.MouseButton.LeftButton)
        self.assertTrue(hst.is_open())
        self.assertTrue(b.isOpen())
        self.assertIs(hst.badge(), b)
        g = hst.card.geometry()
        self.assertEqual(g.top(), b.y() + b.height() + 1)                     # under the badge
        self.assertLessEqual(g.right() + 1, b.x() + b.width())                # at its right
        self.assertTrue(panel.rect().contains(g))
        self.assertEqual(g.width(), W.CARD_W)
        QTest.mouseClick(b, Qt.MouseButton.LeftButton)                        # a second click closes
        self.assertFalse(hst.is_open())
        self.assertFalse(b.isOpen())
        b.setFocus()
        QTest.keyClick(b, Qt.Key.Key_Return)
        self.assertTrue(hst.is_open())
        b.hide()                                                              # the badge goes: the card too
        self.assertFalse(hst.is_open())

    def test_closes_after_the_pointer_left(self):
        panel, hst = self.panel()
        b = self.badge(panel, 200, 100)
        panel.show()
        settle()
        QTest.mouseClick(b, Qt.MouseButton.LeftButton)
        enter(b)
        leave(b)
        self.assertTrue(hst.is_open())                                        # not at once
        self.assertTrue(wait_until(lambda: not hst.is_open(), wait_ms(1000)))
        QTest.mouseClick(b, Qt.MouseButton.LeftButton)
        leave(b)
        enter(hst.card)                                                       # reaching the card keeps it
        QTest.qWait(200)
        self.assertTrue(hst.is_open())
        leave(hst.card)
        self.assertTrue(wait_until(lambda: not hst.is_open(), wait_ms(1000)))
        self.assertFalse(b.isOpen())

    def test_actions_and_moving(self):
        panel, hst = self.panel()
        b = self.badge(panel, 200, 100)
        low = self.badge(panel, 200, 560, [table_card()])
        panel.show()
        settle()
        got = Count(b.actionTriggered)
        QTest.mouseClick(b, Qt.MouseButton.LeftButton)
        primary = [x for x in hst.card.buttons() if x.objectName() == "xsCardPrimary"]
        self.assertEqual([x.text() for x in primary], ["Looks right"])
        primary[0].click()
        self.assertEqual(got.args, [("looks_right",)])
        self.assertFalse(hst.is_open())
        QTest.mouseClick(b, Qt.MouseButton.LeftButton)
        QTest.mouseClick(low, Qt.MouseButton.LeftButton)                      # another badge: the card moves
        self.assertIs(hst.badge(), low)
        self.assertFalse(b.isOpen())
        self.assertTrue(low.isOpen())
        g = hst.card.geometry()
        self.assertEqual(g.bottom() + 1, low.y() - 1)                         # above it, near the bottom
        self.assertEqual(hst.card.titles(), ["3 water levels left out"])
        hst.close()
        self.assertFalse(low.isOpen() or hst.is_open())
        panel.hide()
        QTest.mouseClick(b, Qt.MouseButton.LeftButton)
        self.assertFalse(hst.card.isVisible())

    def test_the_note_keeps_its_padding(self):
        """(fix 0.3.6) The note lines up with the term list above it (11 px in) and keeps 8 px above the footer's
        rule, also after the card's stylesheet is set again (a palette change re-polishes its labels, which reset a
        label's own margins)."""
        panel, hst = self.panel()
        b = self.badge(panel, 120, 40, [table_card()])
        panel.show()
        settle()
        hst.open(b)
        settle()
        card = hst.card
        for step in ("open", "palette"):
            note = card.findChild(QLabel, "xsCardNote")
            term = card.findChildren(QLabel, "xsCardTerm")[0]
            text_x = [w.mapTo(card, QPoint(w.contentsRect().left(), 0)).x() for w in (note, term)]
            self.assertEqual(text_x, [12, 12], step)                                # border 1 + 11
            note_bottom = note.mapTo(card, QPoint(0, note.height() - 1)).y()
            self.assertEqual(card._foot.mapTo(card, QPoint(0, 0)).y() - note_bottom, 8 + 1 + 1, step)   # + the rule
            card.setPalette(night_palette())
            settle()

    def test_card_content_and_width(self):
        card = W.CheckCard()
        blocks = [guess_card(), table_card()]
        card.set_content(blocks, W.card_actions(blocks))
        self.assertEqual(card.objectName(), "xsCheckCard")
        self.assertEqual(card.titles(), ["Fields were guessed", "3 water levels left out"])
        self.assertEqual(card.items(), [("Label", "AESI_MapLabel", ""), ("ATD level", "GW_Elev_ATD", " · elevations"),
                                        ("B-4", '"dry"', ""), ("MW-2", '"n/a"', "")])
        self.assertEqual(card.notes(), ["Only plain numbers are read; 1,234.5 is fine."])
        self.assertEqual([(x.text(), x.objectName()) for x in card.buttons()],
                         [("Open Depths", "xsCardButton"), ("Looks right", "xsCardPrimary"),
                          ("Open Water", "xsCardButton")])
        texts = [x.text() for x in card.findChildren(QLabel)]
        self.assertIn("… and 3 more", texts)
        self.assertIn("Explorations by others · table Boring Summary, field DTW", texts)
        values = [x for x in card.findChildren(W.ElidedLabel) if x.objectName() == "xsCardValue"]
        self.assertTrue(all(v.font().styleHint() == W.QFont.StyleHint.Monospace for v in values))
        card.set_content([table_card()], W.card_actions([table_card()]))
        self.assertEqual([(x.text(), x.objectName()) for x in card.buttons()], [("Open Water", "xsCardPrimary")])
        many = W.CardInfo("12 left out", items=[(f"S-{i}", "empty", "") for i in range(12)], mono=False)
        card.set_content([many])
        self.assertEqual((len(card.items()), card.buttons()), (W.CARD_ITEMS, []))
        self.assertIn("… and 4 more", [x.text() for x in card.findChildren(QLabel)])
        for width, expect in ((340, 272), (260, 252)):
            panel, hst = self.panel(width)
            b = self.badge(panel, 120, 40, blocks)
            panel.show()
            settle()
            hst.open(b)
            self.assertEqual(hst.card.width(), expect)
            self.assertTrue(panel.rect().contains(hst.card.geometry()))
            self.assertGreater(hst.card.height(), 100)


# ================================================================ 13.-14. swatches, labels, SurfaceRow
class Swatches(unittest.TestCase):
    def ink(self, w, color):
        """Pixels that are not the white chip, once the darkest one is `color` (0 when it is not)."""
        img = image(w)
        if dist(darkest(img, 0, w.width()), color) > 60:
            return 0
        white = QColor("#ffffff")
        return sum(1 for x in range(img.width()) for y in range(img.height()) if dist(img.pixelColor(x, y), white) > 60)

    def test_symbol_and_bracket(self):
        s = W.SymbolSwatch()
        self.assertEqual((s.width(), s.height(), s.kind(), s.shape()), (22, 16, "symbol", "asterisk"))
        s.set_symbol("spring", "#1f6fb2")
        self.assertEqual((s.shape(), s.color()), ("spring", "#1f6fb2"))
        self.assertGreater(self.ink(s, "#1f6fb2"), 10)
        s.set_bracket("#7a4fb0", "dash")
        self.assertEqual((s.kind(), s.shape(), s.bracket_style(), s.color()), ("bracket", "", "dash", "#7a4fb0"))
        self.assertGreater(self.ink(s, "#7a4fb0"), 10)
        self.assertEqual(self.ink(s, "#1f6fb2"), 0)
        img = image(s)
        self.assertEqual(img.pixelColor(1, 1).name(), "#ffffff")                # the white chip, no border
        bar = W.BarSwatch("#111111")
        self.assertEqual((bar.width(), bar.height()), (22, 16))
        self.assertLess(dist(px(image(bar), 11, 8), QColor("#111111")), 12)
        dot = W.StatusDot()
        h = host(dot)
        try:
            self.assertTrue(dot.isHidden())
            for state in ("ok", "warn", "error"):
                dot.set_state(state)
                self.assertFalse(dot.isHidden())
                self.assertEqual(dot.state(), state)
            dot.set_state("")
            self.assertTrue(dot.isHidden())
        finally:
            h.close()

    def test_elided_label_key_part_and_amber(self):
        pal = light_palette()
        t = W.theme_for(pal)
        lab = W.ElidedLabel("Name · ground line", small=True)
        lab.setPalette(pal)
        lab.resize(200, lab.height())
        lab.setKeyPart("Name")
        self.assertEqual(lab.keyPart(), "Name")
        fm = QFontMetrics(lab.font())
        img = image(lab)
        key = darkest(img, 0, fm.horizontalAdvance("Name"))
        rest = darkest(img, fm.horizontalAdvance("Name · "), fm.horizontalAdvance("Name · ground line"))
        self.assertLess(dist(key, t.ink2), dist(key, t.muted))
        self.assertLess(dist(rest, t.muted), dist(rest, t.ink2))
        lab.setKeyPart("")
        lab.setAmber(True)
        self.assertLess(dist(darkest(image(lab), 0, 100), t.amber), 40)
        self.assertEqual(lab.text(), "Name · ground line")
        lab.setLineHeight(1.25)
        self.assertEqual(lab.height(), round(lab.font().pointSizeF() * lab.logicalDpiY() / 72.0 * 1.25))

    def test_surface_row(self):
        row = W.SurfaceRow()
        self.assertIsInstance(row, W.LayerCard)
        self.assertEqual(row.objectName(), "xsSurfaceRow")
        self.assertEqual((row.color_btn.width(), row.color_btn.height()), (22, 16))
        self.assertEqual((row.menu_btn.width(), row.menu_btn.height()), (22, 20))
        g = row._grid
        for w in (row.visible_box, row.color_btn, row.name_area, row.badge, row.menu_btn):
            self.assertEqual(g.getItemPosition(g.indexOf(w))[0], 0)            # one header row
        self.assertEqual(g.getItemPosition(g.indexOf(row.problem_label))[:2], (1, 2))
        self.assertEqual(row.editor.objectName(), "xsSurfaceEditor")
        m = row.editor.layout().contentsMargins()
        self.assertEqual((m.left(), m.top(), m.right(), m.bottom(), row.editor.layout().spacing()),
                         (9, 8, 8, 11, 8))
        self.assertEqual(row.name_label.font().weight(), W.QFont.Weight.Normal)
        row.toggle_editor()
        self.assertTrue(row.editor_open())
        self.assertEqual(row.name_label.font().weight(), W.QFont.Weight.DemiBold)
        d = dict(SURFACE_DEFAULTS, name="Till", color="#123456", style="dash", width=1.5, mode="cells",
                 z_units="m", in_range=False, marks=True, visible=False)
        ch = Count(row.changed)
        row.set_value(d)
        self.assertEqual(row.value(), d)
        self.assertEqual(list(row.value()), list(SURFACE_DEFAULTS))
        self.assertEqual(len(ch), 0)


# ================================================================ 15. the stylesheet
class Stylesheet(unittest.TestCase):
    def test_names(self):
        for _name, make in PALETTES:
            sheet = W.panel_stylesheet(W.theme_for(make()))
            for name in ("QLabel#xsHint {", 'QLabel#xsHint[warn="true"]', 'QLabel#xsHint[head="true"]',
                         "QToolButton#xsAdd {", "QToolButton#xsAdd:hover", "QPushButton#xsCardButton",
                         "QPushButton#xsCardPrimary", "QListView#xsSymbolList", "QLabel#xsStatus",
                         "QLabel#xsReadout", "QLabel#xsFieldLabel", "QLabel#xsNote", "QLabel#xsMuted",
                         "QToolButton#xsSegButton", "QToolButton#xsTool", "QToolButton#xsRowMenu",
                         "QToolButton#xsLink", "QPushButton#xsPrimary", "QFrame#xsStyleBox",
                         "QFrame#xsSurfaceList {"):                          # (the Surfaces CSV dialog's list)
                self.assertIn(name, sheet)
            # (fix 0.3.6) the dashed boxes keep a transparent 1 px border here; their dashes are painted (Pieces)
            self.assertIn("QFrame#xsMoreBody { border: 1px solid transparent", sheet)
            self.assertNotIn("1px dashed " + W.theme_for(make()).row_rail.name(), sheet)
            for gone in ("xsSurfaceRow", "xsGroundRow", "xsSurfaceEditor", "xsPointList", "xsPointRow",
                         "xsSubhead", "xsRuleTop", "xsNewBadge", "xsSectionBody", "xsCheckCard"):
                self.assertNotIn(gone, sheet)


if __name__ == "__main__":
    unittest.main()
