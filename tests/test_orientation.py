"""Page orientation (0.3.5, his request): Auto | Landscape | Portrait under Scale & sheet.

"I'd like to be able to control the orientation of the paper pages - i.e. portrait vs. landscape. Right now it is
chosen automatically. ... Auto would work like it does now." Auto is the search of every earlier version (each sheet
landscape, then portrait; tiles landscape, then portrait); Landscape and Portrait use only that orientation, for one
sheet and for tiling alike; a custom page is sized to the drawing and has none. The golden / compat tests
(test_compat_032, test_scales) stay untouched: Auto draws exactly as before."""
import dataclasses
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from tests.fixtures import STANDARD_LAYOUT, default_settings, load_project, start_app

APP = start_app()

from pypdf import PdfReader  # noqa: E402
from qgis.PyQt.QtWidgets import QLabel  # noqa: E402

from tests.test_scales import model, settings  # noqa: E402
from tests.test_ui import make_iface  # noqa: E402
from xsections.core.model import (ORIENTATIONS, SETTINGS_VERSION, Settings, clean_orientation,  # noqa: E402
                                  migrate_settings)
from xsections.render import scales as S  # noqa: E402
from xsections.render.export import export  # noqa: E402
from xsections.render.scales import plan  # noqa: E402
from xsections.ui import dock as D  # noqa: E402
from xsections.ui import settings_store  # noqa: E402
from xsections.ui.dock import XSectionsDock  # noqa: E402

SHORT = dict(z_lo=150.0, z_hi=250.0)                # 4,500 ft, 3 in tall at 1,000 / 50 ft: Letter landscape (Auto)
TALL = dict(hits=[("B-1", 1000.0, 150.0, 95.0)])    # 0..350 ft = 7 in tall: Letter portrait (Auto)
CUSTOM_TIP = "Not used with a custom page size: a custom page is sized to the drawing"


def oriented(s: Settings, orientation) -> Settings:
    return dataclasses.replace(s, orientation=orientation)


def sizes(p):
    return [(pg.page_w, pg.page_h) for pg in p.pages]


class Case(unittest.TestCase):
    def margins_ok(self, pg):
        """The plot inside the standard margins (STANDARD_LAYOUT, 0.5 in printer edge), on 0.01 in."""
        self.assertGreaterEqual(pg.plot_left, S.MARGIN["left"] - 1e-9)
        self.assertLessEqual(pg.plot_left + pg.plot_w, pg.page_w - S.MARGIN["right"] + 1e-9)
        self.assertGreaterEqual(pg.plot_bottom, S.MARGIN["bottom"] - 1e-9)
        self.assertLessEqual(pg.plot_bottom + pg.plot_h, pg.page_h - S.MARGIN["top"] + 1e-9)
        self.assertAlmostEqual(pg.plot_left * 100, round(pg.plot_left * 100), places=6)
        self.assertAlmostEqual(pg.plot_bottom * 100, round(pg.plot_bottom * 100), places=6)


# ------------------------------------------------------------------ plan(): one sheet
class OneSheet(Case):
    def test_page_turns(self):
        self.assertEqual(ORIENTATIONS, ("auto", "landscape", "portrait"))
        for value, turns in (("auto", (True, False)), ("landscape", (True,)), ("portrait", (False,)),
                             ("sideways", (True, False)), ("", (True, False)), (None, (True, False)),
                             (" Portrait ", (False,))):
            self.assertEqual(S.page_turns(oriented(Settings(), value)), turns, value)

    def test_a_short_section(self):
        m = model(**SHORT)
        s = settings(below_in=0.0)
        auto = plan(m, s)
        self.assertEqual((sizes(auto), auto.pages[0].sheet_name), ([(11.0, 8.5)], "Letter 11 × 8.5 in, landscape"))
        self.assertEqual(plan(m, oriented(s, "landscape")), auto)          # the page Auto gives: the same plan
        p = plan(m, oriented(s, "portrait"))
        self.assertTrue(p.fits, p.message)
        pg = p.pages[0]
        self.assertEqual((pg.page_w, pg.page_h, pg.sheet_name), (8.5, 11.0, "Letter 8.5 × 11 in, portrait"))
        self.assertEqual((pg.plot_w, pg.plot_h), (4.5, 3.0))              # the drawing at the same exact scale
        self.assertEqual((p.z_min, p.z_max), (auto.z_min, auto.z_max))
        self.assertEqual(p.message, "Letter 8.5 × 11 in, portrait; plot 4.50 × 3.00 in.")
        self.margins_ok(pg)

    def test_a_tall_section(self):
        m = model(**TALL)
        s = settings()
        auto = plan(m, s)
        self.assertEqual((sizes(auto), auto.pages[0].sheet_name), ([(8.5, 11.0)], "Letter 8.5 × 11 in, portrait"))
        self.assertEqual(plan(m, oriented(s, "portrait")), auto)
        p = plan(m, oriented(s, "landscape"))            # 7 in tall: Letter landscape holds 5 in, Tabloid 7.5 in
        self.assertTrue(p.fits, p.message)
        self.assertEqual((sizes(p), p.pages[0].sheet_name), ([(17.0, 11.0)], "Tabloid 17 × 11 in, landscape"))
        self.assertEqual(p.pages[0].plot_h, 7.0)
        self.margins_ok(p.pages[0])

    def test_a_named_sheet(self):
        m = model(**SHORT)
        for sheet, land, port in (("tabloid", (17.0, 11.0), (11.0, 17.0)), ("archd", (36.0, 24.0), (24.0, 36.0))):
            s = settings(sheet=sheet, below_in=0.0)
            self.assertEqual(sizes(plan(m, s)), [land])
            self.assertEqual(sizes(plan(m, oriented(s, "landscape"))), [land])
            p = plan(m, oriented(s, "portrait"))
            self.assertEqual(sizes(p), [port])
            self.assertTrue(p.pages[0].sheet_name.endswith(", portrait"))

    def test_fill_with_grid_uses_the_page_it_gets(self):
        m = model(**SHORT)
        s = settings(below_in=0.0, fill_grid="below")
        base = plan(m, settings(below_in=0.0))
        land = plan(m, oriented(s, "landscape"))         # 8.5 - 1.2 - 2.3 = 5 in of room: 2 whole majors below
        self.assertEqual((land.z_min, land.z_max, land.pages[0].plot_h), (base.z_min - 100.0, base.z_max, 5.0))
        self.assertEqual(land, plan(m, s))
        port = plan(m, oriented(s, "portrait"))          # 11 - 1.2 - 2.3 = 7.5 in: 4 whole majors below
        self.assertEqual((port.z_min, port.z_max, port.pages[0].plot_h), (base.z_min - 200.0, base.z_max, 7.0))
        self.assertEqual(port.pages[0].plot_bottom, 2.55)               # the 0.5 in left over shared (centred)
        both = plan(m, oriented(settings(below_in=0.0, fill_grid="both"), "portrait"))
        self.assertEqual((both.z_min, both.z_max), (base.z_min - 100.0, base.z_max + 100.0))

    def test_the_compact_layout_and_notes(self):
        """The default layout (compact, filled below) on the page each orientation gives."""
        m = model(**SHORT)
        for o, size in (("landscape", (11.0, 8.5)), ("portrait", (8.5, 11.0))):
            for compact, notes in ((True, True), (False, True), (True, False)):
                s = oriented(Settings(compact_layout=compact, show_notes=notes, below_in=0.0), o)
                p = plan(m, s)
                self.assertTrue(p.fits, (o, compact, notes, p.message))
                self.assertEqual(sizes(p), [size])
                pg = p.pages[0]
                mg = S.margins(s, (p.z_min, p.z_max), S.legend_entries(m, s))
                self.assertGreaterEqual(pg.plot_left, mg["left"] - 1e-9)
                self.assertLessEqual(pg.plot_left + pg.plot_w, pg.page_w - mg["right"] + 1e-9)
                self.assertLessEqual(pg.plot_bottom + pg.plot_h, pg.page_h - mg["top"] + 1e-9)

    def test_an_unknown_orientation_is_auto(self):
        for m in (model(**SHORT), model(**TALL), model(4600.0)):
            s = settings(h_scale=100.0) if m.length > 4500 else settings()
            auto = plan(m, s)
            for bad in ("sideways", "", None, 3):
                self.assertEqual(plan(m, oriented(s, bad)), auto, bad)

    def test_a_custom_page_ignores_it(self):
        m = model(20000.0, 150.0, 250.0)
        s = settings(sheet="custom", below_in=0.0, fill_grid="below")
        auto = plan(m, s)
        self.assertEqual((sizes(auto), auto.pages[0].sheet_name), ([(22.5, 6.5)], "Custom 22.5 × 6.5 in"))
        for o in ("landscape", "portrait"):
            self.assertEqual(plan(m, oriented(s, o)), auto, o)
        small = model(1000.0, 150.0, 200.0)                # the smallest custom page stays 8.5 × 5.5 in
        self.assertEqual(sizes(plan(small, oriented(settings(sheet="custom", below_in=0.0), "portrait"))),
                         [(8.5, 5.5)])


# ------------------------------------------------------------------ plan(): tiled
class Tiled(Case):
    def test_a_long_section_tiles_in_the_chosen_orientation(self):
        m = model(4600.0)
        s = settings(h_scale=100.0)
        auto = plan(m, s)
        self.assertEqual((len(auto.pages), auto.pages[0].sheet_name), (4, "Tabloid 17 × 11 in, landscape"))
        self.assertEqual(plan(m, oriented(s, "landscape")), auto)
        p = plan(m, oriented(s, "portrait"))
        self.assertTrue(p.fits, p.message)
        n = len(p.pages)
        self.assertEqual(n, 8)
        usable = (11.0 - S.MARGIN["left"] - S.MARGIN["right"]) * 100.0
        cores = []
        for i, pg in enumerate(p.pages, 1):
            self.assertEqual((pg.page_w, pg.page_h, pg.sheet_name), (11.0, 17.0, "Tabloid 11 × 17 in, portrait"))
            self.assertEqual((pg.tile_index, pg.tile_count), (i, n))
            self.assertLessEqual(pg.x_max - pg.x_min, usable + 1e-9)
            self.assertAlmostEqual(pg.plot_w, (pg.x_max - pg.x_min) / 100.0)
            self.assertEqual((pg.plot_left, pg.plot_bottom), (p.pages[0].plot_left, p.pages[0].plot_bottom))
            self.margins_ok(pg)
            a = pg.match_left if pg.match_left is not None else 0.0
            b = pg.match_right if pg.match_right is not None else p.plot_length
            cores.append((a, b))
            if pg.match_right is not None:                  # whole-major cores, one major of overlap
                self.assertEqual(pg.x_max - pg.match_right, 100.0)
                self.assertEqual(pg.match_right % 100.0, 0.0)
            if pg.match_left is not None:
                self.assertEqual(pg.match_left - pg.x_min, 100.0)
        self.assertEqual((cores[0][0], cores[-1][1]), (0.0, 4600.0))
        for (_a0, b0), (a1, _b1) in zip(cores, cores[1:]):
            self.assertEqual(b0, a1)
        self.assertEqual(p.message, "Too long for one Tabloid sheet: tiled on 8 sheets (Tabloid 11 × 17 in, "
                                    "portrait), match lines at STA 7+00, 13+00, 19+00, …, 43+00 (7 in all).")

    def test_a_named_sheet_too_short_in_landscape(self):
        """Letter named, 6 in tall: Auto tiles portrait (as before); Landscape cannot (5 in of room) and says so,
        giving only the landscape room and offering Auto or Portrait (which tile)."""
        m = model(4600.0)
        s = settings(h_scale=100.0, sheet="letter")
        auto = plan(m, s)
        self.assertTrue(auto.fits)
        self.assertTrue(all(size == (8.5, 11.0) for size in sizes(auto)))
        self.assertEqual(plan(m, oriented(s, "portrait")), auto)
        p = plan(m, oriented(s, "landscape"))
        self.assertFalse(p.fits)
        self.assertEqual(p.message, "The section is 6.00 in tall at 1 in = 50 ft vertical (elevation 50 to 350 ft), "
                                    "but a Letter sheet has room for 5.00 in (landscape). Choose Auto or Portrait, a "
                                    "smaller vertical scale (more ft per inch), a narrower manual elevation range, a "
                                    "larger sheet, or a custom page size.")
        self.assertEqual(len(p.pages), 1)
        self.assertTrue(p.pages[0].sheet_name.startswith("Needs "))

    def test_too_tall_in_every_orientation(self):
        m = model(4600.0, **TALL)
        s = settings(h_scale=100.0, v_scale=10.0)
        start = ("The section is 21.00 in tall at 1 in = 10 ft vertical (elevation 80 to 290 ft), but a Tabloid sheet "
                 "has room for ")
        end = ("Use a smaller vertical scale (more ft per inch), a narrower manual elevation range, a larger sheet, "
               "or a custom page size.")
        self.assertEqual(plan(m, s).message, start + "7.50 in (landscape) or 13.50 in (portrait). " + end)   # as before
        self.assertEqual(plan(m, oriented(s, "landscape")).message, start + "7.50 in (landscape). " + end)
        self.assertEqual(plan(m, oriented(s, "portrait")).message, start + "13.50 in (portrait). " + end)

    def test_a_grid_too_coarse_for_the_chosen_orientation(self):
        m = model(4600.0)
        grid = dict(grid_auto=False, h_major=300.0, h_minor=30.0, v_major=50.0, v_minor=5.0)
        s = settings(h_scale=100.0, **grid)
        auto = plan(m, s)                                   # 3 in majors: Tabloid landscape tiles
        self.assertTrue(auto.fits)
        self.assertEqual(sizes(auto)[0], (17.0, 11.0))
        p = plan(m, oriented(s, "portrait"))                 # 8.5 in of usable width: less than three majors
        self.assertFalse(p.fits)
        self.assertEqual(p.message, "The grid (major 300 ft = 3 in) is too coarse to tile on Tabloid sheets in "
                                    "portrait. The section needs a 48.75 × 9.5 in page at 1 in = 100 ft horizontal "
                                    "and 1 in = 50 ft vertical (plot 46.20 × 6.00 in). Choose Auto or Landscape, a "
                                    "smaller major grid, a larger sheet, or a custom page size.")
        coarse = settings(h_scale=100.0, **dict(grid, h_major=1000.0, h_minor=100.0))
        self.assertEqual(plan(m, coarse).message,                            # Auto: as before
                         "The grid (major 1,000 ft = 10 in) is too coarse to tile on Tabloid sheets. The section "
                         "needs a 48.5 × 9.5 in page at 1 in = 100 ft horizontal and 1 in = 50 ft vertical (plot "
                         "46.00 × 6.00 in). Choose a smaller major grid, a larger sheet, or a custom page size.")
        self.assertEqual(plan(m, oriented(coarse, "landscape")).message,     # nothing to offer
                         "The grid (major 1,000 ft = 10 in) is too coarse to tile on Tabloid sheets in landscape. The "
                         "section needs a 48.5 × 9.5 in page at 1 in = 100 ft horizontal and 1 in = 50 ft vertical "
                         "(plot 46.00 × 6.00 in). Choose a smaller major grid, a larger sheet, or a custom page size.")


# ------------------------------------------------------------------ plan(): nothing fits, tiling off
class NoFit(Case):
    def test_auto_word_for_word(self):
        p = plan(model(4600.0), settings(h_scale=100.0, tile=False))
        self.assertEqual(p.message, "The section needs a 48.5 × 9.5 in page at 1 in = 100 ft horizontal and 1 in = "
                                    "50 ft vertical (plot 46.00 × 6.00 in), larger than Letter or Tabloid in either "
                                    "orientation. Choose a custom page size, a larger sheet, a smaller scale (more ft "
                                    "per inch), or turn on tiling.")

    def test_portrait_names_itself_and_offers_landscape(self):
        m = model(9000.0, 150.0, 250.0)                      # 9 in wide: Tabloid landscape, not Tabloid portrait
        s = settings(below_in=0.0, tile=False)
        self.assertEqual(sizes(plan(m, s)), [(17.0, 11.0)])
        p = plan(m, oriented(s, "portrait"))
        self.assertFalse(p.fits)
        self.assertEqual(p.message, "The section needs a 11.5 × 6.5 in page at 1 in = 1,000 ft horizontal and 1 in = "
                                    "50 ft vertical (plot 9.00 × 3.00 in), larger than Letter or Tabloid in portrait. "
                                    "Choose Auto or Landscape, a custom page size, a larger sheet, a smaller scale "
                                    "(more ft per inch), or turn on tiling.")
        self.assertEqual((p.pages[0].page_w, p.pages[0].page_h), (11.5, 6.5))       # the page it would need

    def test_nothing_offered_when_the_other_would_not_fit_either(self):
        m = model(4600.0)
        for o in ("landscape", "portrait"):
            p = plan(m, oriented(settings(h_scale=100.0, tile=False), o))
            self.assertFalse(p.fits)
            self.assertEqual(p.message, "The section needs a 48.5 × 9.5 in page at 1 in = 100 ft horizontal and 1 in "
                                        f"= 50 ft vertical (plot 46.00 × 6.00 in), larger than Letter or Tabloid in {o}. "
                                        "Choose a custom page size, a larger sheet, a smaller scale (more ft per "
                                        "inch), or turn on tiling.")


# ------------------------------------------------------------------ the setting
class SettingsKey(unittest.TestCase):
    def test_default_and_place(self):
        self.assertEqual(Settings().orientation, "auto")
        self.assertEqual(SETTINGS_VERSION, 7)                     # a new key with a default: no version step
        names = [f.name for f in dataclasses.fields(Settings)]
        self.assertEqual(names[names.index("sheet") + 1], "orientation")
        self.assertEqual(list(json.loads(Settings().to_json()))[names.index("sheet") + 1], "orientation")

    def test_clean_orientation(self):
        for value, want in (("auto", "auto"), ("landscape", "landscape"), ("portrait", "portrait"),
                            ("Portrait", "portrait"), (" LANDSCAPE ", "landscape"), ("sideways", "auto"),
                            ("", "auto"), (None, "auto"), (5, "auto"), (True, "auto"), (["portrait"], "auto")):
            self.assertEqual(clean_orientation(value), want, value)

    def test_json_round_trip_and_bad_values(self):
        for o in ORIENTATIONS:
            self.assertEqual(Settings.from_json(Settings(orientation=o).to_json()).orientation, o)
        data = json.loads(Settings().to_json())
        for bad, want in (("sideways", "auto"), (5, "auto"), (None, "auto"), ("Portrait", "portrait")):
            self.assertEqual(Settings.from_json(json.dumps(dict(data, orientation=bad))).orientation, want, bad)
            self.assertEqual(migrate_settings(dict(data, orientation=bad))["orientation"], want, bad)
        # older settings (no key) take Auto: the search they were planned with
        old = {k: v for k, v in data.items() if k != "orientation"}
        self.assertNotIn("orientation", migrate_settings(old))
        self.assertEqual(Settings.from_json(json.dumps(old)).orientation, "auto")
        self.assertEqual(Settings.from_json(json.dumps(dict(old, version=5))).orientation, "auto")

    def test_the_project_store(self):
        prj = load_project()[0]
        for o in ORIENTATIONS:
            s = Settings(h_scale=200.0, orientation=o)
            settings_store.save(prj, s)
            self.assertEqual(settings_store.load(prj).orientation, o)
            self.assertEqual(json.loads(settings_store.stored_json(prj))["orientation"], o)
        data = json.loads(Settings().to_json())
        for bad in ("upside down", 3, [], None):
            prj.writeEntry(settings_store.SCOPE, settings_store.KEY, json.dumps(dict(data, orientation=bad, v_scale=20)))
            s = settings_store.load(prj)
            self.assertEqual((s.orientation, s.v_scale), ("auto", 20.0), bad)       # the rest still applies
        settings_store.clear(prj)


# ------------------------------------------------------------------ the panel
class Panel(unittest.TestCase):
    def setUp(self):
        self.prj, self.dem, self.pts, self.lines = load_project()
        self.dock = XSectionsDock(make_iface(), None)
        self.dock.restore_from_project()
        self.addCleanup(self._drop, self.dock)

    @staticmethod
    def _drop(d):
        d.cleanup()
        d.deleteLater()
        APP.processEvents()

    def new_dock(self) -> XSectionsDock:
        d = XSectionsDock(make_iface(), None)
        self.addCleanup(self._drop, d)
        d.restore_from_project()
        return d

    @staticmethod
    def click(seg, data) -> None:
        seg.buttons()[seg.findData(data)].click()

    def test_the_control(self):
        d = self.dock
        seg = d.orientation
        self.assertTrue(d.grp_export.isAncestorOf(seg))
        self.assertEqual([seg.itemText(i) for i in range(seg.count())], ["Auto", "Landscape", "Portrait"])
        self.assertEqual([seg.itemData(i) for i in range(seg.count())], ["auto", "landscape", "portrait"])
        self.assertEqual([b.toolTip() for b in seg.buttons()],
                         ["As fits best: landscape first, then portrait (as before)", "Every sheet landscape",
                          "Every sheet portrait"])
        self.assertEqual((seg.currentData(), d.settings().orientation), ("auto", "auto"))     # the default
        box = seg.parentWidget()
        head = next(lab for lab in box.findChildren(QLabel) if lab.objectName() == "xsFieldLabel")
        self.assertEqual(head.text(), "Orientation")
        # a row of its own, right under Size | Format (0.3.6: in Scale & sheet › Sheet, Title after it), the full
        # width of the section
        sheet_pair = d.sheet.parentWidget().parentWidget()
        sub = sheet_pair.parentWidget()
        self.assertEqual(sub.title(), "Sheet")
        lay = sub.body_layout
        self.assertTrue(sheet_pair.isAncestorOf(d.fmt))
        self.assertEqual(lay.indexOf(box), lay.indexOf(sheet_pair) + 1)
        self.assertEqual(lay.indexOf(d.title_text.parentWidget()), lay.indexOf(box) + 1)
        for width in (340, 260):
            d.resize(width, 900)
            d.show()
            d.grp_export.setCollapsed(False)
            APP.processEvents()
            self.assertEqual(box.width(), sheet_pair.width())
            self.assertGreater(box.y(), sheet_pair.y())
            for b in seg.buttons():                         # every word whole
                self.assertLessEqual(b.fontMetrics().horizontalAdvance(b.text()) + 6, b.width(), (width, b.text()))
            self.assertFalse(d.scroll.horizontalScrollBar().isVisible())
        d.hide()

    def test_off_for_a_custom_page(self):
        d = self.dock
        seg = d.orientation
        self.click(seg, "portrait")
        for sheet in ("custom", "letter", "custom", "smallest"):
            custom = sheet == "custom"                      # (0.3.7: the Size list's check boxes)
            d.sheet.setChecks(["letter", "tabloid"] if sheet == "smallest" else [sheet], custom=custom, emit=True)
            self.assertEqual(seg.isEnabled(), not custom, sheet)
            tips = [b.toolTip() for b in seg.buttons()]
            if custom:
                self.assertEqual(tips, [CUSTOM_TIP] * 3)
                self.assertEqual(seg.toolTip(), CUSTOM_TIP)
            else:
                self.assertEqual(tips, D.ORIENT_TIPS)
            head = next(lab for lab in seg.parentWidget().findChildren(QLabel) if lab.objectName() == "xsFieldLabel")
            self.assertEqual(head.isEnabled(), not custom)             # the label greys out with it
            self.assertEqual(d.settings().orientation, "portrait")      # kept for when he leaves Custom
        d.apply_settings(dataclasses.replace(d.settings(), sheet="custom"))
        self.assertFalse(seg.isEnabled())

    def test_saved_and_restored_with_the_project(self):
        d = self.dock
        d._timer.stop()
        d._user_changed = False
        self.click(d.orientation, "portrait")
        self.assertTrue(d._user_changed and d._timer.isActive())       # saved and rebuilt like the other sheet keys
        with mock.patch.object(d, "refresh"):
            d._timer.stop()
            d._on_timer()
        self.assertEqual(json.loads(settings_store.stored_json(self.prj))["orientation"], "portrait")
        self.assertEqual(settings_store.load(self.prj).orientation, "portrait")
        other = self.new_dock()
        self.assertEqual((other.orientation.currentData(), other.settings().orientation), ("portrait", "portrait"))
        # shown and read back
        for o in ORIENTATIONS:
            d.apply_settings(dataclasses.replace(d.settings(), orientation=o))
            self.assertEqual((d.orientation.currentData(), d.settings().orientation), (o, o))
        d.apply_settings(dataclasses.replace(d.settings(), orientation="sideways"))
        self.assertEqual(d.orientation.currentData(), "auto")
        d.apply_settings(dataclasses.replace(d.settings(), orientation="landscape"))
        d.project_cleared()                                            # a closed project: the default
        self.assertEqual(d.orientation.currentData(), "auto")

    def test_a_click_rebuilds_on_the_chosen_page(self):
        d = self.dock
        d.apply_settings(default_settings(self.prj, self.dem, self.pts, self.lines, h_scale=1000.0, v_scale=50.0,
                                          **STANDARD_LAYOUT))
        d.refresh()
        self.assertEqual(d.last_error, "")
        self.assertEqual(d.plan.pages[0].sheet_name, "Letter 11 × 8.5 in, landscape")
        self.assertIn("Sheet: <b>Letter 11 × 8.5 in, landscape</b>", d.export_readout.text())
        before = d.plan
        self.click(d.orientation, "portrait")
        self.assertTrue(d._timer.isActive())                           # the debounced rebuild, not at once
        self.assertIs(d.plan, before)
        with mock.patch.object(d, "isVisible", return_value=True):
            d._timer.stop()
            d._on_timer()
        pg = d.plan.pages[0]
        self.assertEqual((pg.page_w, pg.page_h, pg.sheet_name), (8.5, 11.0, "Letter 8.5 × 11 in, portrait"))
        self.assertEqual((pg.plot_w, pg.plot_h), (before.pages[0].plot_w, before.pages[0].plot_h))
        self.assertIn("Sheet: <b>Letter 8.5 × 11 in, portrait</b>", d.export_readout.text())
        self.assertEqual(d.grp_export.chipText(), "1,000′ / 50′ · Letter")          # the chip names the sheet
        self.assertEqual(settings_store.load(self.prj).orientation, "portrait")
        # tiled on portrait sheets: 1 in = 100 ft
        d.h_scale.setEditText("100")
        d.refresh()
        p = d.plan
        self.assertTrue(p.fits, p.message)
        self.assertGreater(len(p.pages), 1)
        self.assertTrue(all(pg.page_w < pg.page_h and pg.sheet_name.endswith(", portrait") for pg in p.pages))
        self.assertIn(f"<b>{len(p.pages)} sheets</b>", d.export_readout.text())
        self.click(d.orientation, "landscape")
        d.refresh()
        self.assertTrue(all(pg.page_w > pg.page_h and pg.sheet_name.endswith(", landscape") for pg in d.plan.pages))


# ------------------------------------------------------------------ export
class ExportPages(Case):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="xsec_orient_")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def boxes(self, path):
        return [[float(v) for v in pg.mediabox] for pg in PdfReader(path).pages]

    def test_a_pdf_page_has_the_orientation(self):
        m = model(**SHORT)
        s = settings(below_in=0.0)
        for o, size in (("auto", (11.0, 8.5)), ("landscape", (11.0, 8.5)), ("portrait", (8.5, 11.0))):
            p = plan(m, oriented(s, o))
            self.assertEqual(sizes(p), [size])
            out = export(m, oriented(s, o), p, os.path.join(self.dir, f"{o}.pdf"), "pdf")
            self.assertEqual(self.boxes(out[0]), [[0.0, 0.0, size[0] * 72, size[1] * 72]], o)

    def test_tiled_pdf_pages_are_portrait(self):
        m = model(4600.0)
        s = oriented(settings(h_scale=100.0), "portrait")
        p = plan(m, s)
        out = export(m, s, p, os.path.join(self.dir, "tiled.pdf"), "pdf")
        self.assertEqual(self.boxes(out[0]), [[0.0, 0.0, 11.0 * 72, 17.0 * 72]] * len(p.pages))
        self.assertEqual(len(p.pages), 8)

    def test_png_size_follows(self):
        m = model(**SHORT)
        s = oriented(settings(below_in=0.0), "portrait")
        p = plan(m, s)
        out = export(m, s, p, os.path.join(self.dir, "p.png"), "png", 100)
        from tests import measure as M
        _rgb, info = M.load_png(out[0])
        self.assertEqual(info["size"], (850, 1100))


if __name__ == "__main__":
    unittest.main()
