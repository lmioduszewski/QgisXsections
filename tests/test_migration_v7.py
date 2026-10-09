"""Settings version 7 (0.3.4, DESIGN.md decision 23). The sheet-style keys: the grid (Green | Gray | Custom, the
Custom grid's colours, widths and line styles) and the depth line widths, their defaults (0.3.3's look: Green, 0.75 /
1.6 pt), the helpers the sheet and the preview read them through (grid_spec, depth_widths) and the cleaning of stored
values on every load (clean_sheet_style, through Settings.from_json and settings_store.load). The version 7 step:
"Data lines: By type" leaves Sheet style, its Black rows become Color (each exploration's colour from the layer's own
style), and data_color is gone from Settings. A row's 0.3.3 picked colour (its `color` key) is dropped on load."""
import json
import math
import os
import unittest
from types import SimpleNamespace

from tests.fixtures import start_app

APP = start_app()

from qgis.core import QgsProject  # noqa: E402

from xsections.core.model import (DEPTH_LW_BLACK, DEPTH_LW_COLOR, DEPTH_LW_LIMITS, GRID_CHOICES,  # noqa: E402
                                  GRID_PRESETS, GRID_STYLES, GRID_W_MAX, GRID_W_MIN, POINT_LAYER_DEFAULTS,
                                  SETTINGS_VERSION, SURFACE_STYLES, Settings, clean_sheet_style, depth_widths,
                                  grid_spec, migrate_settings)
from xsections.ui import settings_store  # noqa: E402

NEW_KEYS = ("grid_major_color", "grid_major_width", "grid_major_style", "grid_minor_color", "grid_minor_width",
            "grid_minor_style", "grid_custom_used", "depth_lw_black", "depth_lw_color")
GREEN = GRID_PRESETS["green"]


def custom(**kw):
    """Settings with the Custom grid and `kw`."""
    return Settings(grid_color="custom", **kw)


class SheetStyleKeys(unittest.TestCase):
    """The new keys (stage A of 0.3.4): defaults, helpers and the cleaner."""

    def test_constants(self):
        self.assertEqual(GRID_CHOICES, ("green", "gray", "custom"))
        self.assertEqual(GRID_STYLES, SURFACE_STYLES)
        self.assertEqual(GRID_STYLES, ("solid", "dash", "dot"))
        self.assertEqual(GRID_PRESETS, {"green": (("#5f9a72", 0.7, "solid"), ("#a8c8b2", 0.35, "solid")),
                                        "gray": (("#6e6e6e", 0.7, "solid"), ("#b4b4b4", 0.35, "solid"))})
        self.assertEqual((GRID_W_MIN, GRID_W_MAX), (0.1, 3.0))
        self.assertEqual((DEPTH_LW_BLACK, DEPTH_LW_COLOR), (0.75, 1.6))
        self.assertEqual(DEPTH_LW_LIMITS, {"depth_lw_black": (0.25, 3.0), "depth_lw_color": (0.25, 4.0)})

    def test_defaults(self):
        """Green, the custom keys at the Green values, not used yet, 0.75 / 1.6 pt: 0.3.3's look."""
        s = Settings()
        self.assertEqual(s.grid_color, "green")
        self.assertEqual((s.grid_major_color, s.grid_major_width, s.grid_major_style), ("#5f9a72", 0.7, "solid"))
        self.assertEqual((s.grid_minor_color, s.grid_minor_width, s.grid_minor_style), ("#a8c8b2", 0.35, "solid"))
        self.assertIs(s.grid_custom_used, False)
        self.assertEqual((s.depth_lw_black, s.depth_lw_color), (0.75, 1.6))
        self.assertEqual(grid_spec(s), GREEN)
        self.assertEqual(depth_widths(s), (0.75, 1.6))
        for k in NEW_KEYS:                       # flat scalars (settings_store._coerce has no dict branch)
            self.assertIsInstance(getattr(s, k), (str, float, bool), k)
        names = [f for f in json.loads(s.to_json())]
        i = names.index("grid_color")
        self.assertEqual(names[i + 1:i + 1 + len(NEW_KEYS)], list(NEW_KEYS))          # right after grid_color

    def test_grid_spec(self):
        self.assertEqual(grid_spec(Settings(grid_color="green")), GREEN)
        self.assertEqual(grid_spec(Settings(grid_color="gray")), GRID_PRESETS["gray"])
        # a preset ignores the custom keys (they are only the remembered Custom values)
        self.assertEqual(grid_spec(Settings(grid_color="gray", grid_major_color="#123456", grid_major_width=2.0,
                                            grid_minor_style="dot")), GRID_PRESETS["gray"])
        self.assertEqual(grid_spec(custom()), GREEN)                                   # the custom defaults
        self.assertEqual(grid_spec(custom(grid_major_color="#1F6FB2", grid_major_width=1.5, grid_major_style="dash",
                                          grid_minor_color="#c2185b", grid_minor_width=0.2,
                                          grid_minor_style="dot")),
                         (("#1f6fb2", 1.5, "dash"), ("#c2185b", 0.2, "dot")))
        for bad in ("neon", "", "Custom", "GREEN", None, 3):                            # unknown: Green
            self.assertEqual(grid_spec(SimpleNamespace(grid_color=bad)), GREEN, bad)
        # bad custom values: the Green colour, clamped widths (not a number: the Green width), solid
        got = grid_spec(custom(grid_major_color="red", grid_major_width=9.0, grid_major_style="wavy",
                               grid_minor_color="#12345", grid_minor_width=0.01, grid_minor_style=""))
        self.assertEqual(got, (("#5f9a72", 3.0, "solid"), ("#a8c8b2", 0.1, "solid")))
        for w in (math.nan, math.inf, -math.inf, "1", None, True):
            got = grid_spec(SimpleNamespace(grid_color="custom", grid_major_width=w, grid_minor_width=w))
            self.assertEqual((got[0][1], got[1][1]), (0.7, 0.35), w)
        # a hand-made object without the keys: the Green values
        self.assertEqual(grid_spec(SimpleNamespace(grid_color="custom")), GREEN)
        self.assertEqual(grid_spec(SimpleNamespace()), GREEN)

    def test_depth_widths(self):
        self.assertEqual(depth_widths(Settings(depth_lw_black=1.0, depth_lw_color=2.25)), (1.0, 2.25))
        self.assertEqual(depth_widths(Settings(depth_lw_black=0.1, depth_lw_color=0.1)), (0.25, 0.25))
        self.assertEqual(depth_widths(Settings(depth_lw_black=9.0, depth_lw_color=9.0)), (3.0, 4.0))
        self.assertEqual(depth_widths(Settings(depth_lw_black=3.5, depth_lw_color=3.5)), (3.0, 3.5))
        for w in (math.nan, math.inf, "2", None, True, False):
            self.assertEqual(depth_widths(SimpleNamespace(depth_lw_black=w, depth_lw_color=w)), (0.75, 1.6), w)
        self.assertEqual(depth_widths(SimpleNamespace()), (0.75, 1.6))
        self.assertEqual(depth_widths(SimpleNamespace(depth_lw_black=2, depth_lw_color=3)), (2.0, 3.0))

    def test_clean_sheet_style(self):
        """In place: bad kinds dropped, widths clamped, colours lower-cased, unknown styles dropped; absent keys stay
        absent."""
        d = {"grid_color": "custom", "grid_major_color": "#ABCDEF", "grid_minor_color": "#12345g",
             "grid_major_width": 7, "grid_minor_width": 0.0, "grid_major_style": "dot", "grid_minor_style": "dotted",
             "grid_custom_used": True, "depth_lw_black": 0.05, "depth_lw_color": 4.5, "tolerance_ft": "x"}
        clean_sheet_style(d)
        self.assertEqual(d, {"grid_color": "custom", "grid_major_color": "#abcdef", "grid_major_width": 3.0,
                             "grid_minor_width": 0.1, "grid_major_style": "dot", "grid_custom_used": True,
                             "depth_lw_black": 0.25, "depth_lw_color": 4.0, "tolerance_ft": "x"})
        self.assertIsInstance(d["grid_major_width"], float)
        d = {"grid_color": "purple", "grid_major_width": True, "grid_minor_width": math.nan, "depth_lw_black": "1",
             "depth_lw_color": None, "grid_custom_used": "yes", "grid_major_color": 0x5f9a72, "grid_major_style": None}
        clean_sheet_style(d)
        self.assertEqual(d, {})
        d = {}
        clean_sheet_style(d)
        self.assertEqual(d, {})
        d = {"grid_color": "gray", "depth_lw_black": 1, "depth_lw_color": 2.25}
        clean_sheet_style(d)
        self.assertEqual(d, {"grid_color": "gray", "depth_lw_black": 1.0, "depth_lw_color": 2.25})
        before = dict(d)
        clean_sheet_style(d)                                                           # idempotent
        self.assertEqual(d, before)

    def test_every_load_cleans(self):
        """Settings.from_json and settings_store.load agree: bad values take their defaults or are clamped, at any
        stored version."""
        stored = {"grid_color": "custom", "grid_major_color": "#ABCDEF", "grid_minor_color": "blue",
                  "grid_major_width": 12.0, "grid_minor_width": "thin", "grid_major_style": "dash",
                  "grid_minor_style": "zigzag", "grid_custom_used": 1, "depth_lw_black": -3.0,
                  "depth_lw_color": 2.5, "tolerance_ft": 80.0}
        prj = QgsProject.instance()
        try:
            for version in (3, 5, 6, 7):
                text = json.dumps(dict(stored, version=version))
                prj.clear()
                prj.writeEntry(settings_store.SCOPE, settings_store.KEY, text)
                for how, s in (("from_json", Settings.from_json(text)), ("store", settings_store.load(prj))):
                    with self.subTest(version=version, how=how):
                        self.assertEqual(s.grid_color, "custom")
                        self.assertEqual((s.grid_major_color, s.grid_major_width, s.grid_major_style),
                                         ("#abcdef", 3.0, "dash"))
                        self.assertEqual((s.grid_minor_color, s.grid_minor_width, s.grid_minor_style),
                                         ("#a8c8b2", 0.35, "solid"))                   # dropped: the defaults
                        self.assertIs(s.grid_custom_used, False)                      # 1 is not a bool
                        self.assertEqual((s.depth_lw_black, s.depth_lw_color), (0.25, 2.5))
                        self.assertEqual(s.tolerance_ft, 80.0)
                        self.assertEqual(grid_spec(s), (("#abcdef", 3.0, "dash"), ("#a8c8b2", 0.35, "solid")))
            # an unknown grid choice: Green
            text = json.dumps({"grid_color": "neon", "version": 6})
            prj.clear()
            prj.writeEntry(settings_store.SCOPE, settings_store.KEY, text)
            for s in (Settings.from_json(text), settings_store.load(prj)):
                self.assertEqual((s.grid_color, grid_spec(s)), ("green", GREEN))
        finally:
            prj.clear()

    def test_older_settings_take_the_defaults(self):
        """A stored grid Green / Gray of 0.3.3 (version 6, no new keys): the same preset, the custom keys at the
        Green values, not used, 0.75 / 1.6 pt; nothing else changes."""
        for grid in ("green", "gray"):
            data = json.loads(Settings(grid_color=grid).to_json())
            for k in NEW_KEYS:
                data.pop(k)
            data["version"] = 6
            s = Settings.from_json(json.dumps(data))
            self.assertEqual(s, Settings(grid_color=grid), grid)
            self.assertEqual(grid_spec(s), GRID_PRESETS[grid])
            self.assertEqual(depth_widths(s), (0.75, 1.6))
            migrated = migrate_settings(data)
            self.assertFalse(set(NEW_KEYS) & set(migrated), grid)                      # absent keys stay absent

    def test_round_trip(self):
        s = custom(grid_major_color="#1f6fb2", grid_major_width=1.25, grid_major_style="dash",
                   grid_minor_color="#c2185b", grid_minor_width=0.5, grid_minor_style="dot", grid_custom_used=True,
                   depth_lw_black=1.0, depth_lw_color=2.25)
        self.assertEqual(Settings.from_json(s.to_json()), s)
        prj = QgsProject.instance()
        try:
            prj.clear()
            settings_store.save(prj, s)
            self.assertEqual(settings_store.load(prj), s)
        finally:
            prj.clear()



GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "compat_032")


def v6_rows(data_color, looks=("black", "gray", "color", "black")):
    """Stored version 6 settings (0.3.3) with one row per look and `data_color` (None: no key)."""
    rows = [dict(POINT_LAYER_DEFAULTS, layer_id=f"L{i}", look=look) for i, look in enumerate(looks)]
    for row in rows:
        if row["look"] == "color":
            row["color"] = "#123456"                  # (a 0.3.3 Color row stored its picked colour)
    data = {"version": 6, "point_layers": rows, "tolerance_ft": 80.0, "grid_color": "gray"}
    if data_color is not None:
        data["data_color"] = data_color
    return data


class DataLinesBecomeRows(unittest.TestCase):
    """The version 7 step (stage B of 0.3.4): "Data lines: By type" turns the Black rows to Color, and the key goes."""

    def test_version(self):
        self.assertEqual(SETTINGS_VERSION, 7)
        self.assertEqual(Settings().version, 7)
        self.assertNotIn("data_color", json.loads(Settings().to_json()))
        with self.assertRaises(TypeError):
            Settings(data_color="type")

    def test_by_type_rows(self):
        """v6 rows with By type: Black -> Color, Gray and Color kept, the key gone; the other keys as stored."""
        data = v6_rows("type")
        out = migrate_settings(data)
        self.assertEqual([r["look"] for r in out["point_layers"]], ["color", "gray", "color", "color"])
        self.assertNotIn("data_color", out)
        self.assertEqual((out["version"], out["tolerance_ft"], out["grid_color"]), (7, 80.0, "gray"))
        self.assertEqual(data["data_color"], "type")                       # the caller's dict is left alone
        self.assertEqual([r["look"] for r in data["point_layers"]], ["black", "gray", "color", "black"])
        s = Settings.from_json(json.dumps(data))
        self.assertEqual([r["look"] for r in s.point_layers], ["color", "gray", "color", "color"])
        self.assertFalse(hasattr(s, "data_color"))

    def test_black_or_no_key_leaves_the_rows_alone(self):
        for data_color in ("black", None, "purple"):
            out = migrate_settings(v6_rows(data_color))
            self.assertEqual([r["look"] for r in out["point_layers"]], ["black", "gray", "color", "black"], data_color)
            self.assertNotIn("data_color", out)

    def test_idempotent(self):
        once = migrate_settings(v6_rows("type"))
        self.assertEqual(migrate_settings(once), once)
        self.assertEqual(migrate_settings(json.loads(json.dumps(once))), once)

    def test_the_bytype_golden_becomes_one_color_row(self):
        """tests/data/compat_032/bytype.json (0.3.2, version 5, flat keys, data_color "type"): the version 6 fold
        makes its row first, then it turns Color; the other golden cases stay one Black row."""
        with open(os.path.join(GOLDEN, "bytype.json"), encoding="utf-8") as fh:
            text = fh.read()
        stored = json.loads(text)
        self.assertEqual((stored["version"], stored["data_color"]), (5, "type"))
        s = Settings.from_json(text)
        self.assertEqual(len(s.point_layers), 1)
        row = s.point_layers[0]
        self.assertEqual((row["layer_id"], row["look"], row["label_field"], row["type_field"], row["types"]),
                         ("{pts}", "color", "ExploName", "ExploType", ["Boring", "Monitoring Well", "CPT"]))
        self.assertEqual((s.version, s.points_layer_id, s.grid_color), (7, "", "green"))
        self.assertEqual(depth_widths(s), (0.75, 1.6))
        for case in ("basic", "manual"):
            with open(os.path.join(GOLDEN, f"{case}.json"), encoding="utf-8") as fh:
                other = Settings.from_json(fh.read())
            self.assertEqual([r["look"] for r in other.point_layers], ["black"], case)

    def test_the_store_agrees(self):
        prj = QgsProject.instance()
        try:
            with open(os.path.join(GOLDEN, "bytype.json"), encoding="utf-8") as fh:
                golden = fh.read()
            for text in (json.dumps(v6_rows("type")), json.dumps(v6_rows("black")), golden):
                prj.clear()
                prj.writeEntry(settings_store.SCOPE, settings_store.KEY, text)
                self.assertEqual(settings_store.load(prj), Settings.from_json(text))
        finally:
            prj.clear()


class RowColourKey(unittest.TestCase):
    """(stage C of 0.3.4) A 0.3.3 row's picked colour: the row key is gone, a Color row takes its colours from the
    layer style."""

    def test_the_color_key_is_dropped(self):
        self.assertNotIn("color", POINT_LAYER_DEFAULTS)
        data = v6_rows(None)
        self.assertEqual(data["point_layers"][2]["color"], "#123456")
        prj = QgsProject.instance()
        try:
            prj.clear()
            prj.writeEntry(settings_store.SCOPE, settings_store.KEY, json.dumps(data))
            for s in (Settings.from_json(json.dumps(data)), settings_store.load(prj)):
                self.assertEqual([r["look"] for r in s.point_layers], ["black", "gray", "color", "black"])
                self.assertFalse(any("color" in r for r in s.point_layers))
                self.assertEqual(list(s.point_layers[2]), list(POINT_LAYER_DEFAULTS))
                self.assertFalse(any("color" in r for r in json.loads(s.to_json())["point_layers"]))
        finally:
            prj.clear()
        # By type too: the Black rows turn Color, none keeps a colour key
        out = migrate_settings(v6_rows("type"))
        self.assertEqual([("color" in r, r["look"]) for r in out["point_layers"]],
                         [(False, "color"), (False, "gray"), (False, "color"), (False, "color")])


if __name__ == "__main__":
    unittest.main()
