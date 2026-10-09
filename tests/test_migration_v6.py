"""Settings version 6 (0.3.3, DESIGN.md decision 22): an older project's single explorations layer becomes the first
exploration row with the same fields, types, water-level table and ATD values; loading an older project never dirties
it; the first save writes the current version. The 0.3.2 texts used here are the golden ones of tests/data/compat_032 (read
only), with their layer-id placeholders filled in."""
import json
import os
import unittest
from unittest import mock

from tests.fixtures import default_settings, explo_row, load_project, start_app

APP = start_app()

from qgis.core import QgsProject  # noqa: E402

from tests.test_ui import fake_model, fake_plan, make_iface  # noqa: E402
from xsections.core.model import (FLAT_LAYER_KEYS, NO_ATD, NO_TYPES, OTHER_POINT_DEFAULTS,  # noqa: E402
                                  POINT_LAYER_DEFAULTS, SETTINGS_VERSION, Settings, as_rows, layer_rows,
                                  migrate_settings)
from xsections.ui import settings_store  # noqa: E402
from xsections.ui.dock import XSectionsDock  # noqa: E402

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "compat_032")
IDS = {"{dem}": "dem_1", "{pts}": "pts_1", "{lines}": "lines_1", "{wells}": "wells_1", "{table}": "table_1"}


def golden_v5(case: str) -> str:
    """The v5 JSON 0.3.2 wrote for a compat case, with made-up layer ids."""
    with open(os.path.join(GOLDEN, f"{case}.json"), encoding="utf-8") as fh:
        text = fh.read()
    for k, v in IDS.items():
        text = text.replace(k, v)
    return text


def v5_text(s: Settings) -> str:
    """`s` as 0.3.2 stored it: version 5, without the 0.3.3 keys."""
    d = json.loads(s.to_json())
    for k in ("point_layers", "other_points", "hidden_points"):
        d.pop(k)
    d["version"] = 5
    return json.dumps(d)


WELLS = dict(points_layer_id="wells_1", label_field="ExploName", type_field="", top_field="ExploElev",
             depth_field="ExploDepth", screen_top_field="ScrTop", screen_bottom_field="ScrBot",
             screen_values="elevation", wl_values="depth", wl_field="WL_Elev", wl_date_field="WL_Date",
             atd_field="ATD", atd_date_field="ATD_Date", wl_table_id="table_1", wl_table_name_field="Boring",
             wl_table_elev_field="WL_Elev", wl_table_date_field="Date", wl_table_kind_field="Kind",
             wl_atd_values=["ATD", "Drilling"], wl_label="elev_date", dem_layer_id="dem_1", line_layer_id="lines_1",
             line_fid=1)


class Migration(unittest.TestCase):
    def test_version(self):
        self.assertGreaterEqual(SETTINGS_VERSION, 6)                 # 6 (0.3.3) or later
        self.assertEqual(Settings().version, SETTINGS_VERSION)

    def test_one_layer_becomes_the_first_row(self):
        """The golden 0.3.2 text of the basic case (explicit types) and of the wells case (table, screens): one row,
        black, the layer's own name, ticked and in the range, with every field as stored; the flat keys dropped."""
        for case, want in (("basic", dict(layer_id="pts_1", label_field="ExploName", type_field="ExploType",
                                          types=["Boring", "Monitoring Well", "CPT"], top_field="ExploElev",
                                          bottom_elev_field="BotElev", depth_field="ExploDepth")),
                           ("wells", dict(layer_id="wells_1", screen_top_field="ScrTop", wl_field="WL_Elev",
                                          wl_table_id="table_1", wl_table_kind_field="Kind", wl_atd_values=[]))):
            text = golden_v5(case)
            stored = json.loads(text)
            s = Settings.from_json(text)
            self.assertEqual(s.version, SETTINGS_VERSION, case)
            self.assertEqual(len(s.point_layers), 1, case)
            row = s.point_layers[0]
            self.assertEqual(list(row), list(POINT_LAYER_DEFAULTS), case)            # cleaned, in key order
            self.assertEqual((row["visible"], row["name"], row["look"], row["in_range"]), (True, "", "black", True))
            for flat, key in FLAT_LAYER_KEYS.items():                                 # every stored field kept
                self.assertEqual(row[key], stored[flat], (case, key))
            for key, v in want.items():
                self.assertEqual(row[key], v, (case, key))
            d = Settings()
            self.assertEqual({k: getattr(s, k) for k in FLAT_LAYER_KEYS}, {k: getattr(d, k) for k in FLAT_LAYER_KEYS})
            self.assertEqual((s.other_points, s.hidden_points), ([], []))
            self.assertEqual(s.label_vertical, stored["label_vertical"])             # shared keys untouched

    def test_table_and_atd_values(self):
        """A wells layer with its water-level table and chosen ATD values, through from_json and the store."""
        s5 = Settings(**WELLS)
        text = v5_text(s5)
        prj = QgsProject.instance()
        prj.clear()
        prj.writeEntry(settings_store.SCOPE, settings_store.KEY, text)
        for s in (Settings.from_json(text), settings_store.load(prj)):
            row = layer_rows(s)[0]
            self.assertEqual(len(s.point_layers), 1)
            for flat, key in FLAT_LAYER_KEYS.items():
                self.assertEqual(row[key], getattr(s5, flat), key)
            self.assertEqual((row["wl_table_id"], row["wl_atd_values"]), ("table_1", ["ATD", "Drilling"]))
            self.assertEqual(s.wl_label, "elev_date")
            self.assertEqual(s, as_rows(s5))
        prj.clear()

    def test_version_1_folds(self):
        """Version 1 (one bottom field and its mode): the bottom-field step runs first, then the row is made."""
        old = {"version": 1, "points_layer_id": "pts_1", "label_field": "ExploName", "bottom_mode": "elevation",
               "bottom_field": "BotElev", "types": ["Boring"]}
        row = layer_rows(Settings.from_json(json.dumps(old)))[0]
        self.assertEqual((row["bottom_elev_field"], row["depth_field"], row["types"]), ("BotElev", "", ["Boring"]))
        row = layer_rows(Settings.from_json(json.dumps(dict(old, bottom_mode="depth"))))[0]
        self.assertEqual((row["bottom_elev_field"], row["depth_field"]), ("", "BotElev"))

    def test_rows_win_over_flat_keys(self):
        """Version 6 data with rows: the rows are the one source (any flat keys are dropped)."""
        rows = [dict(POINT_LAYER_DEFAULTS, layer_id="a", label_field="Name"),
                dict(POINT_LAYER_DEFAULTS, layer_id="b", look="gray", in_range=False, visible=False)]
        data = dict(json.loads(Settings().to_json()), point_layers=rows, points_layer_id="old", label_field="X",
                    types=["Y"], wl_atd_values=[NO_ATD])
        s = Settings.from_json(json.dumps(data))
        self.assertEqual(s.point_layers, rows)
        self.assertEqual((s.points_layer_id, s.label_field, s.types, s.wl_atd_values), ("", "", [], []))
        self.assertNotIn("points_layer_id", migrate_settings(data))

    def test_ground_only(self):
        """No layer (the golden ground case keeps its other flat keys): no rows, the flat keys left as stored."""
        text = golden_v5("ground")
        s = Settings.from_json(text)
        self.assertEqual((s.point_layers, layer_rows(s)), ([], []))
        self.assertEqual((s.points_layer_id, s.label_field, s.types), ("", "ExploName", ["Boring", "Monitoring Well",
                                                                                          "CPT"]))

    def test_bad_kinds_fall_back(self):
        """Wrong kinds and unknown choices take the defaults, row by row and key by key (from_json and the store)."""
        data = {"version": 5, "points_layer_id": "pts_1", "types": "Boring", "label_field": 3, "wl_values": "feet",
                "screen_values": None, "wl_atd_values": [1, 2]}
        row = layer_rows(Settings.from_json(json.dumps(data)))[0]
        self.assertEqual((row["types"], row["label_field"], row["wl_values"], row["screen_values"],
                          row["wl_atd_values"]), ([], "", "elevation", "depth", []))
        bad = {"version": 6, "point_layers": [{"layer_id": "a", "look": "purple", "color": "red", "types": [1]}, "x"],
               "other_points": [{"layer_id": "s", "shape": "hexagon", "size": 99, "elev": "sky"}, 5],
               "hidden_points": ["L#1|a|3", "L#1|a|x", "nope", 7, "L#1|a|3.0", "drawn|b|-2"]}
        prj = QgsProject.instance()
        prj.clear()
        prj.writeEntry(settings_store.SCOPE, settings_store.KEY, json.dumps(bad))
        for s in (Settings.from_json(json.dumps(bad)), settings_store.load(prj)):
            self.assertEqual(len(s.point_layers), 1)
            self.assertEqual((s.point_layers[0]["look"], s.point_layers[0]["types"]), ("black", []))
            self.assertNotIn("color", s.point_layers[0])
            o = s.other_points
            self.assertEqual((len(o), o[0]["shape"], o[0]["size"], o[0]["elev"]), (1, "asterisk", 20.0, "line"))
            self.assertEqual(list(o[0]), list(OTHER_POINT_DEFAULTS))
            self.assertEqual(s.hidden_points, ["L#1|a|3", "drawn|b|-2"])
        prj.writeEntry(settings_store.SCOPE, settings_store.KEY, json.dumps(dict(bad, point_layers="x",
                                                                                 hidden_points={"a": 1})))
        s = settings_store.load(prj)
        self.assertEqual((s.point_layers, s.hidden_points), ([], []))
        prj.clear()

    def test_as_rows_invariant(self):
        """Settings.from_json(x.to_json()) == as_rows(x) for v5 Settings: the fixture's default settings, the wells
        and table case, a ground line only, and flat keys without a layer."""
        prj, dem, pts, lines = load_project()
        cases = [default_settings(prj, dem, pts, lines),
                 default_settings(prj, dem, pts, lines, types=["Boring", NO_TYPES], bottom_elev_field="BotElev"),
                 Settings(**WELLS),
                 Settings(dem_layer_id=dem.id()),
                 Settings(label_field="ExploName", types=["Boring"], wl_field="WL", wl_atd_values=["ATD"])]
        for x in cases:
            self.assertEqual(Settings.from_json(x.to_json()), as_rows(x))
            self.assertEqual(Settings.from_json(v5_text(x)), as_rows(x))
        self.assertIs(as_rows(cases[3]), cases[3])
        self.assertEqual(as_rows(cases[0]).point_layers, layer_rows(cases[0]))


class OpeningAnOlderProject(unittest.TestCase):
    """Opening a 0.3.2 project shows it as rows and never dirties it; the first change the user makes saves v6."""

    def setUp(self):
        self.prj, self.dem, self.pts, self.lines = load_project()
        self.s5 = default_settings(self.prj, self.dem, self.pts, self.lines, types=["Boring", "CPT"],
                                   tolerance_ft=90.0)
        self.text = v5_text(self.s5)
        self.prj.writeEntry(settings_store.SCOPE, settings_store.KEY, self.text)
        self.prj.setDirty(False)
        self.iface = make_iface()
        self.dock = XSectionsDock(self.iface, None)
        self.dock._pipeline = lambda _s: (fake_model(), fake_plan())

    def tearDown(self):
        self.dock.cleanup()
        self.dock.deleteLater()
        APP.processEvents()
        self.prj.clear()

    def test_load_then_save_is_stable(self):
        d = self.dock
        d.restore_from_project()
        self.assertEqual(d.settings(), as_rows(self.s5))
        self.assertEqual(len(d.explo_rows), 1)
        self.assertEqual(explo_row(d).type_list.checked_types(), ["Boring", "CPT"])
        d.refresh()
        d._on_timer()
        self.assertFalse(self.prj.isDirty(), "opening and refreshing an older project must not dirty it")
        self.assertEqual(settings_store.stored_json(self.prj), self.text)          # still the 0.3.2 text
        # the first user change writes the current version; saving again changes nothing
        d.tolerance.setValue(80.0)
        d._on_timer()
        saved = json.loads(settings_store.stored_json(self.prj))
        self.assertEqual(saved["version"], SETTINGS_VERSION)
        self.assertEqual(saved["point_layers"], layer_rows(self.s5))
        self.assertEqual(saved["points_layer_id"], "")
        self.assertTrue(self.prj.isDirty())
        text = settings_store.stored_json(self.prj)
        self.assertFalse(d.save_settings())                                        # unchanged: not rewritten
        self.assertEqual(settings_store.stored_json(self.prj), text)
        other = XSectionsDock(self.iface, None)
        try:
            other.restore_from_project()
            self.assertEqual(other.settings(), d.settings())
            other._user_changed = True
            self.assertFalse(other.save_settings())                                # the same text again
        finally:
            other.cleanup()
            other.deleteLater()

    def test_project_write_keeps_it(self):
        """Saving the project (writeProject) stores the panel's settings again: as v6 rows, the same section."""
        d = self.dock
        d.restore_from_project()
        with mock.patch.object(settings_store, "save", wraps=settings_store.save) as save:
            d._on_write_project()
        save.assert_called_once()
        self.assertEqual(settings_store.load(self.prj), as_rows(self.s5))
        self.assertEqual(json.loads(settings_store.stored_json(self.prj))["version"], SETTINGS_VERSION)


if __name__ == "__main__":
    unittest.main()
