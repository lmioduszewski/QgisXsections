"""Several exploration layers (0.3.3, DESIGN.md decision 22), the core part: the settings rows and their cleaners, the
row helpers (layer_rows, layer_view, hit_settings, line_key, as_rows), the per-row build, the type filter with
"(no value)", the left-off list, dates stored as epoch milliseconds, the per-row hover lookups and the speed budgets."""
import dataclasses
import json
import math
import time
import unittest
from unittest import mock

from tests.fixtures import (CELL, CRS, TOLERANCE, budget, default_settings, load_project, make_dense_layer,
                            make_others_layer, make_supply_layer, plane_z, point_at, point_row, single_renderer,
                            start_app, timing_test, write_gpkg)
from tests.test_units import FTUS

APP = start_app()

from qgis.core import (QgsCoordinateReferenceSystem, QgsFeature, QgsField, QgsProject,  # noqa: E402
                       QgsVectorLayer)
from qgis.PyQt.QtCore import QMetaType  # noqa: E402

from xsections.core import build as B  # noqa: E402
from xsections.core import explorations as E  # noqa: E402
from xsections.core import hover as H  # noqa: E402
from xsections.core.build import build_section  # noqa: E402
from xsections.core.model import (FLAT_LAYER_KEYS, LOOK_GRAY, NO_ATD, NO_POINTS,  # noqa: E402
                                  NO_TYPES, OTHER_POINT_DEFAULTS, POINT_LAYER_DEFAULTS, Hit, SectionError,
                                  Settings, as_rows, clean_hidden, clean_other_point, clean_other_points,
                                  clean_point_layer, clean_point_layers, hidden_key, hit_settings, layer_rows,
                                  layer_view, line_key, point_legend_name, row_from_flat)
from xsections.core.section import ground_profile, raster_sampler, resolve_line  # noqa: E402
from xsections.ui import settings_store  # noqa: E402

PLOTTED = ["B-1", "MW-1", "TP-1", "B-2", "MW-2", "CPT-1", "B-3"]


def explo_row(pts, **kw):
    """The fixtures' explorations as a row (the fields of default_settings)."""
    base = dict(label_field="ExploName", type_field="ExploType", top_field="ExploElev", depth_field="ExploDepth")
    base.update(kw)
    return point_row(pts, **base)


def others_row(layer, **kw):
    base = dict(label_field="ExploName", type_field="ExploType_resolved", top_field="ExploElev",
                depth_field="ExploDepth")
    base.update(kw)
    return point_row(layer, **base)


def supply_row(layer, **kw):
    base = dict(label_field="AESI_MapLabel", type_field="ExploType_resolved", top_field="ExploElev",
                depth_field="WellCompleteDepth", atd_field="GW_Elev_ATD", atd_date_field="ExploDate")
    base.update(kw)
    return point_row(layer, **base)


def rows_settings(prj, dem, lines, rows, **kw):
    """Settings as the panel writes them: the rows, the flat per-layer keys at their defaults."""
    s = Settings(line_layer_id=lines.id(), line_fid=next(lines.getFeatures()).id(), dem_layer_id=dem.id(),
                 tolerance_ft=TOLERANCE, point_layers=list(rows))
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def by_label(hits):
    return {h.label: h for h in hits}


# ===================================================================================================== settings
class Cleaners(unittest.TestCase):
    def test_point_layer_defaults_and_key_order(self):
        self.assertEqual(clean_point_layer({}), POINT_LAYER_DEFAULTS)
        d = clean_point_layer({"wl_atd_values": ["ATD"], "layer_id": "L", "extra": 1, "look": "gray"})
        self.assertEqual(list(d), list(POINT_LAYER_DEFAULTS))
        self.assertNotIn("extra", d)
        self.assertEqual((d["layer_id"], d["look"], d["wl_atd_values"]), ("L", "gray", ["ATD"]))
        self.assertEqual(list(POINT_LAYER_DEFAULTS)[:5], ["layer_id", "visible", "name", "look", "in_range"])
        self.assertEqual(set(FLAT_LAYER_KEYS.values()) | {"visible", "name", "look", "in_range"},
                         set(POINT_LAYER_DEFAULTS))
        self.assertEqual(len(FLAT_LAYER_KEYS), 21)
        self.assertEqual(FLAT_LAYER_KEYS["points_layer_id"], "layer_id")
        self.assertIsNone(clean_point_layer("x"))
        self.assertIsNone(clean_point_layer(None))

    def test_point_layer_kinds_and_choices(self):
        d = clean_point_layer({"look": "neon", "color": "#ABCDEF", "screen_values": "feet", "wl_values": "x",
                               "visible": "yes", "in_range": 0, "types": "Boring", "label_field": 5,
                               "wl_atd_values": ["ATD", 3]})
        self.assertEqual((d["look"], d["screen_values"], d["wl_values"]), ("black", "depth", "elevation"))
        self.assertEqual((d["visible"], d["in_range"], d["types"], d["label_field"], d["wl_atd_values"]),
                         (True, True, [], "", []))
        d = clean_point_layer({"look": "color", "color": "#1F6FB2", "screen_values": "elevation",
                               "wl_values": "depth", "visible": False, "in_range": False,
                               "types": ["Boring", ""], "wl_atd_values": [NO_ATD]})
        self.assertEqual((d["look"], d["screen_values"], d["wl_values"], d["visible"], d["in_range"]),
                         ("color", "elevation", "depth", False, False))
        self.assertEqual((d["types"], d["wl_atd_values"]), (["Boring", ""], [NO_ATD]))

    def test_lists_are_new_lists(self):
        a = clean_point_layer({})
        b = clean_point_layer({})
        self.assertIsNot(a["types"], POINT_LAYER_DEFAULTS["types"])
        self.assertIsNot(a["types"], b["types"])
        a["types"].append("x")
        a["wl_atd_values"].append("y")
        self.assertEqual((POINT_LAYER_DEFAULTS["types"], POINT_LAYER_DEFAULTS["wl_atd_values"]), ([], []))
        self.assertEqual(clean_point_layer({})["types"], [])
        given = {"types": ["Boring"]}
        d = clean_point_layer(given)
        self.assertIsNot(d["types"], given["types"])
        self.assertIsNot(clean_other_point({})["types"], OTHER_POINT_DEFAULTS["types"])

    def test_point_layer_lists(self):
        self.assertEqual(clean_point_layers("x"), [])
        self.assertEqual(clean_point_layers(None), [])
        self.assertEqual(clean_point_layers([{"layer_id": "a"}, 3, None, "b", {"look": "gray"}]),
                         [dict(POINT_LAYER_DEFAULTS, layer_id="a"), dict(POINT_LAYER_DEFAULTS, look="gray")])

    def test_other_point(self):
        self.assertEqual(clean_other_point({}), OTHER_POINT_DEFAULTS)
        self.assertEqual(OTHER_POINT_DEFAULTS["shape"], "asterisk")
        self.assertEqual((OTHER_POINT_DEFAULTS["color"], OTHER_POINT_DEFAULTS["size"]), ("#1f6fb2", 7.0))
        self.assertEqual(OTHER_POINT_DEFAULTS["elev"], "line")
        d = clean_other_point({"elev_empty": "lidar", "shape": "hexagon", "elev": "dem", "color": "#00FF00",
                               "size": 12, "x": 1, "layer_id": "S"})
        self.assertEqual(list(d), list(OTHER_POINT_DEFAULTS))
        self.assertEqual((d["shape"], d["elev"], d["elev_empty"], d["color"], d["size"], d["layer_id"]),
                         ("asterisk", "line", "lidar", "#00ff00", 12.0, "S"))
        self.assertIsInstance(d["size"], float)
        for size, want in ((2, 3.0), (25, 20.0), (0, 3.0), (-4.0, 3.0), (3, 3.0), (20.0, 20.0), (7.5, 7.5),
                           ("7", 7.0), (True, 7.0), (math.nan, 7.0), (math.inf, 7.0), (None, 7.0)):
            self.assertEqual(clean_other_point({"size": size})["size"], want, size)
        for shape in ("circle", "square", "diamond", "star", "triangle"):
            self.assertEqual(clean_other_point({"shape": shape})["shape"], shape)
        for elev, empty in (("lidar", "off"), ("field", "line")):
            d = clean_other_point({"elev": elev, "elev_empty": empty})
            self.assertEqual((d["elev"], d["elev_empty"]), (elev, empty))
        self.assertEqual(clean_other_point({"elev_empty": "never"})["elev_empty"], "line")
        self.assertEqual(clean_other_point({"color": "blue"})["color"], "#1f6fb2")
        self.assertIsNone(clean_other_point([]))
        self.assertEqual(clean_other_points({"a": 1}), [])
        self.assertEqual(clean_other_points([{}, 1]), [OTHER_POINT_DEFAULTS])

    def test_hidden(self):
        for bad in ("a|b|1", None, {"a": 1}, 3):
            self.assertEqual(clean_hidden(bad), [])
        got = clean_hidden(["lines_1#3|pts_2|12", "drawn|pts_2|-5", "drawn|pts_2|007", "drawn|pts_2|7",
                            "a|b|c", "|L|3", "k||3", "k|L|3.5", "k|L|", "k|L| 4", "k|L", 5, None,
                            "lines_1#3|pts_2|12", "x|y|z|9"])
        self.assertEqual(got, sorted({"lines_1#3|pts_2|12", "drawn|pts_2|-5", "drawn|pts_2|7", "x|y|z|9"}))
        self.assertEqual(got, sorted(got))
        self.assertEqual(clean_hidden(["k|L|-0"]), ["k|L|0"])


class RowHelpers(unittest.TestCase):
    FLAT = dict(points_layer_id="pts", label_field="Name", type_field="Kind", types=["A", ""], top_field="Top",
                bottom_elev_field="Bot", depth_field="Dep", screen_top_field="ST", screen_bottom_field="SB",
                screen_values="elevation", wl_values="depth", wl_field="WL", wl_date_field="WLD", atd_field="ATD",
                atd_date_field="ATDD", wl_table_id="tbl", wl_table_name_field="TN", wl_table_elev_field="TE",
                wl_table_date_field="TD", wl_table_kind_field="TK", wl_atd_values=["ATD"])

    def flat(self, **kw):
        return Settings(tolerance_ft=80.0, td_label=False, **dict(self.FLAT, **kw))

    def test_flat_names_every_per_layer_key(self):
        self.assertEqual(set(self.FLAT), set(FLAT_LAYER_KEYS))
        names = {f.name for f in dataclasses.fields(Settings)}
        self.assertTrue(set(FLAT_LAYER_KEYS) <= names)
        self.assertEqual([f.name for f in dataclasses.fields(Settings)][
            [f.name for f in dataclasses.fields(Settings)].index("label_vertical") + 1:][:3],
            ["point_layers", "other_points", "hidden_points"])
        s = Settings()
        self.assertEqual((s.point_layers, s.other_points, s.hidden_points), ([], [], []))

    def test_row_from_flat(self):
        row = row_from_flat(self.flat())
        self.assertEqual(list(row), list(POINT_LAYER_DEFAULTS))
        self.assertEqual((row["layer_id"], row["look"], row["name"], row["visible"], row["in_range"]),
                         ("pts", "black", "", True, True))
        for k, v in FLAT_LAYER_KEYS.items():
            self.assertEqual(row[v], self.FLAT[k], k)
        self.assertIsNot(row["types"], self.FLAT["types"])

    def test_layer_rows(self):
        s = self.flat()
        self.assertEqual(layer_rows(s), [row_from_flat(s)])
        self.assertEqual(layer_rows(Settings()), [])
        self.assertEqual(layer_rows(self.flat(points_layer_id="")), [])      # flat keys without a layer: none
        rows = [{"layer_id": "a", "look": "neon"}, 4, {"layer_id": "b", "visible": False}]
        s = self.flat(point_layers=rows)                                       # rows win over the flat keys
        self.assertEqual(layer_rows(s), [dict(POINT_LAYER_DEFAULTS, layer_id="a"),
                                         dict(POINT_LAYER_DEFAULTS, layer_id="b", visible=False)])
        self.assertEqual(rows[0]["look"], "neon")                              # the stored rows are not changed

    def test_layer_view_equals_the_flat_settings(self):
        s = self.flat()
        view = layer_view(s, row_from_flat(s))
        for f in dataclasses.fields(Settings):
            self.assertEqual(getattr(view, f.name), getattr(s, f.name), f.name)
        self.assertEqual(view, s)
        # a row's fields over shared settings with the flat keys at their defaults
        row = point_row(layer_id="other", top_field="ExploElev", types=["Boring"], wl_atd_values=[NO_ATD])
        rs = Settings(tolerance_ft=80.0, screens=False, point_layers=[row])
        view = layer_view(rs, row)
        self.assertEqual((view.points_layer_id, view.top_field, view.types, view.wl_atd_values),
                         ("other", "ExploElev", ["Boring"], [NO_ATD]))
        self.assertEqual((view.tolerance_ft, view.screens), (80.0, False))
        self.assertIsNot(view.types, row["types"])
        self.assertEqual(rs.top_field, "")                                     # rs itself unchanged

    def test_hit_settings(self):
        r0 = point_row(layer_id="L0", top_field="T0")
        r1 = point_row(layer_id="L1", top_field="T1")
        s = Settings(point_layers=[r0, r1])
        hit = lambda **kw: mock.Mock(**kw)                                   # noqa: E731 (duck-typed Hit)
        self.assertEqual(hit_settings(s, hit(layer_index=1, layer_id="L1")).top_field, "T1")
        self.assertEqual(hit_settings(s, hit(layer_index=1, layer_id="")).top_field, "T1")
        self.assertEqual(hit_settings(s, hit(layer_index=1, layer_id="L0")).top_field, "T0")   # rows reordered
        self.assertIs(hit_settings(s, hit(layer_index=5, layer_id="")), s)
        self.assertIs(hit_settings(s, hit(layer_index=0, layer_id="gone")), s)
        self.assertEqual(hit_settings(s, hit(layer_index=7, layer_id="L1")).top_field, "T1")
        flat = Settings(top_field="ExploElev")                                 # no layer: s itself
        self.assertIs(hit_settings(flat, Hit(0, "x", "", 0, 0, 0, 0, "L", "", 0, 0, None, "none", None)), flat)
        flat = self.flat()
        self.assertEqual(hit_settings(flat, Hit(0, "x", "", 0, 0, 0, 0, "L", "", 0, 0, None, "none", None)), flat)

    def test_line_key_hidden_key_and_names(self):
        self.assertEqual(line_key(Settings(line_layer_id="lines_1", line_fid=3)), "lines_1#3")
        self.assertEqual(line_key(Settings(line_layer_id="lines_1", line_fid=0, line_wkt="LineString (0 0, 1 1)")),
                         "lines_1#0")                                          # a picked feature wins
        self.assertEqual(line_key(Settings(line_wkt="LineString (0 0, 1 1)")), "drawn")
        self.assertEqual(line_key(Settings(line_layer_id="lines_1", line_wkt="LineString (0 0, 1 1)")), "drawn")
        self.assertEqual(line_key(Settings(line_layer_id="lines_1")), "")
        self.assertEqual(line_key(Settings()), "")
        self.assertEqual(hidden_key("lines_1#3", "pts_2", 12), "lines_1#3|pts_2|12")
        self.assertEqual(clean_hidden([hidden_key("drawn", "pts", -1)]), ["drawn|pts|-1"])
        self.assertEqual(point_legend_name({"name": "  Others "}, "Explor_Other_pt"), "Others")
        self.assertEqual(point_legend_name({"name": " "}, "Explor_Other_pt"), "Explor_Other_pt")
        self.assertEqual(point_legend_name({}, "L"), "L")

    def test_as_rows(self):
        s = self.flat()
        r = as_rows(s)
        self.assertEqual(r.point_layers, [row_from_flat(s)])
        d = Settings()
        for k in FLAT_LAYER_KEYS:
            self.assertEqual(getattr(r, k), getattr(d, k), k)
        self.assertEqual((r.tolerance_ft, r.td_label), (80.0, False))           # shared keys kept
        none = self.flat(points_layer_id="")
        self.assertIs(as_rows(none), none)                                     # no layer: s itself
        rows = Settings(point_layers=[point_row(layer_id="a")], tolerance_ft=60.0)
        self.assertEqual(as_rows(rows), rows)                                  # rows: unchanged
        self.assertEqual(as_rows(as_rows(s)), as_rows(s))
        self.assertEqual(layer_rows(as_rows(s)), layer_rows(s))


class Store(unittest.TestCase):
    """settings_store: the three new keys round-trip, and fall back to [] when of the wrong kind."""

    def setUp(self):
        self.prj = QgsProject.instance()
        self.prj.clear()

    def tearDown(self):
        self.prj.clear()

    def test_round_trip(self):
        s = Settings(point_layers=[point_row(layer_id="a", look="color", types=["Boring", ""]),
                                   point_row(layer_id="b", visible=False, in_range=False, wl_atd_values=[NO_ATD])],
                     other_points=[clean_other_point({"layer_id": "s", "shape": "star", "size": 9.5})],
                     hidden_points=["drawn|a|3", "lines#1|b|-2"])
        self.assertTrue(settings_store.save(self.prj, s))
        back = settings_store.load(self.prj)
        self.assertEqual(back, s)
        self.assertEqual(Settings.from_json(s.to_json()), s)
        self.assertFalse(settings_store.save(self.prj, back))                  # unchanged: not written again
        data = json.loads(settings_store.stored_json(self.prj))
        self.assertEqual(list(data["point_layers"][0]), list(POINT_LAYER_DEFAULTS))
        self.assertEqual(list(data["other_points"][0]), list(OTHER_POINT_DEFAULTS))

    def test_stored_rows_are_cleaned(self):
        data = json.loads(Settings().to_json())
        data.update(point_layers=[{"layer_id": "a", "look": "neon", "color": "#ABCDEF"}, 3],
                    other_points=[{"layer_id": "s", "size": 99}, "x"],
                    hidden_points=["drawn|a|007", "bad", "drawn|a|7", 4])
        self.prj.writeEntry(settings_store.SCOPE, settings_store.KEY, json.dumps(data))
        s = settings_store.load(self.prj)
        self.assertEqual(s.point_layers, [dict(POINT_LAYER_DEFAULTS, layer_id="a")])
        self.assertEqual(s.other_points, [dict(OTHER_POINT_DEFAULTS, layer_id="s", size=20.0)])
        self.assertEqual(s.hidden_points, ["drawn|a|7"])

    def test_bad_kinds_fall_back_to_defaults(self):
        for key, bad in (("point_layers", "Boring"), ("point_layers", {"layer_id": "a"}), ("point_layers", 3),
                         ("other_points", "x"), ("other_points", None), ("hidden_points", "drawn|a|1"),
                         ("hidden_points", {"x": 1})):
            data = json.loads(Settings().to_json())
            data[key] = bad
            data["tolerance_ft"] = 77.0
            self.prj.writeEntry(settings_store.SCOPE, settings_store.KEY, json.dumps(data))
            s = settings_store.load(self.prj)
            self.assertEqual(getattr(s, key), [], (key, bad))
            self.assertEqual(s.tolerance_ft, 77.0)                             # the rest still applies


# ===================================================================================================== the build
class RowsBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        cls.others = make_others_layer()
        cls.supply = make_supply_layer()
        cls.prj.addMapLayers([cls.others, cls.supply])

    def settings(self, rows, **kw):
        return rows_settings(self.prj, self.dem, self.lines, rows, **kw)

    def build(self, rows, **kw):
        s = self.settings(rows, **kw)
        return build_section(s, self.prj), s

    def three(self):
        return [explo_row(self.pts), others_row(self.others), supply_row(self.supply)]

    def test_three_rows_are_the_sum_of_each_row_alone(self):
        m, s = self.build(self.three())
        alone = [self.build([r])[0] for r in self.three()]
        self.assertEqual(len(m.hits), sum(len(a.hits) for a in alone))
        self.assertEqual(len(m.hits), 7 + 5 + 4)                              # O-far is near; HW-far far away
        names = ["Explorations", "Explorations by others", "Supply wells"]
        for i, a in enumerate(alone):
            mine = [h for h in m.hits if h.layer_index == i]
            self.assertEqual([h.label for h in mine], [h.label for h in a.hits], i)
            for h, g in zip(mine, a.hits):
                self.assertEqual(dataclasses.replace(h, layer_index=0), g, h.label)   # the same in every field
                self.assertEqual((h.layer_id, h.layer_name), (self.three()[i]["layer_id"], names[i]))
            info = m.point_layers[i]
            self.assertEqual((info.index, info.name, info.layer_name, info.on, info.plotted, info.left_off),
                             (i, names[i], names[i], True, len(a.hits), 0))
            self.assertEqual((info.look, info.color, info.in_range), ("black", "", True))
            self.assertEqual(info.near, a.near_count)
        self.assertEqual(m.near_count, sum(a.near_count for a in alone))
        self.assertEqual(m.near_count, 1)                                      # O-far (300 ft)
        self.assertEqual(m.beyond_ends, [f"{b} (Explorations)" for b in alone[0].beyond_ends])
        self.assertEqual(alone[0].beyond_ends, ["B-pre", "B-post"])           # one row: plain labels, as before
        self.assertEqual([h.station for h in m.hits], sorted(h.station for h in m.hits))
        self.assertEqual([(h.station, h.layer_index, h.label) for h in m.hits],
                         sorted((h.station, h.layer_index, h.label) for h in m.hits))
        self.assertTrue(m.has_explorations)
        self.assertEqual(m.points_name, "Explorations")
        self.assertEqual(m.line_key, line_key(s))
        self.assertEqual(m.left_off, [])
        self.assertEqual([o for o in m.other_layers], [])
        self.assertNotIn(NO_POINTS, m.warnings)
        text = "\n".join(m.warnings)
        self.assertIn("MW-2: ExploElev 205.6 ft ignored", text)
        self.assertIn("Left out past the ends of the line: B-pre (Explorations), B-post (Explorations).", text)

    def test_everything_chosen_is_plotted(self):
        """B-2 and B-2x (0.6 ft apart, two layers) are both plotted: no de-duplication (decision 4)."""
        m, _ = self.build(self.three())
        b2, b2x = by_label(m.hits)["B-2"], by_label(m.hits)["B-2x"]
        self.assertLess(abs(b2.station - b2x.station), 0.01)
        self.assertAlmostEqual(abs(b2.offset - b2x.offset), 0.6 * FTUS, delta=1e-6)
        self.assertEqual((b2.layer_index, b2x.layer_index), (0, 1))
        # the same layer in two rows: each row plots its own explorations
        m, _ = self.build([explo_row(self.pts), explo_row(self.pts, name="Again")])
        self.assertEqual([h.label for h in m.hits if h.layer_index == 1], PLOTTED)
        self.assertEqual(len(m.hits), 2 * len(PLOTTED))
        self.assertEqual(m.point_layers[1].name, "Again")

    def test_each_row_reads_its_own_fields(self):
        m, _ = self.build(self.three())
        by = by_label(m.hits)
        hw1, hw2, sw1, hw3 = by["HW-1"], by["HW-2"], by["SW-1"], by["HW-3"]
        x, y = point_at(1800.0, 60.0)
        self.assertEqual(hw1.total_depth, 400.0)                               # WellCompleteDepth (ExploDepth 380)
        self.assertEqual((hw1.top_source, hw1.bottom_source), ("field", "depth"))
        self.assertAlmostEqual(hw1.bottom, hw1.top - 400.0, delta=1e-9)
        self.assertEqual([(w.kind, w.source, w.date) for w in hw1.water_levels], [("atd", "GW_Elev_ATD", "2/2/2021")])
        self.assertAlmostEqual(hw1.water_levels[0].elev, round(plane_z(x, y) - 30.0, 2), delta=1e-9)
        self.assertEqual(hw2.total_depth, 42.0)
        self.assertEqual(hw2.top_source, "dem")                                # ExploElev NULL: LIDAR
        self.assertEqual(hw2.water_levels, [])                                  # GW_Elev_ATD 0: missing (shared rule)
        self.assertEqual(hw3.water_levels[0].date, "5/16/1958")                 # before 1970
        self.assertIsNone(sw1.total_depth)                                      # no WellCompleteDepth
        self.assertTrue(any(f.startswith("no bottom elevation or depth (WellCompleteDepth") for f in sw1.flags),
                        sw1.flags)
        self.assertEqual(by["B-1"].total_depth, 30.0)                           # the first row: ExploDepth
        self.assertTrue(all(not h.water_levels for h in m.hits if h.layer_index != 2))
        # zero_is_missing is shared: HW-2's 0 becomes a value, far below the bottom (left out, flagged)
        m, _ = self.build(self.three(), zero_is_missing=False)
        hw2 = by_label(m.hits)["HW-2"]
        self.assertEqual(hw2.water_levels, [])
        self.assertTrue(any("ATD water level 0 ft is below the bottom" in f for f in hw2.flags), hw2.flags)
        self.assertTrue(any("TP-1" == h.label and "ExploElev 0 ft ignored" in " ".join(h.flags) for h in m.hits))
        # the tolerance is shared: at 70 ft each row loses its further explorations
        m, _ = self.build(self.three(), tolerance_ft=70.0)
        self.assertEqual(sorted(h.label for h in m.hits),
                         sorted(["B-1", "MW-1", "TP-1", "CPT-1", "B-3", "O-1", "O-2", "O-4", "HW-1", "SW-1"]))

    def test_the_top_rule_is_shared(self):
        supply = make_supply_layer(name="Supply wells 2")
        self.prj.addMapLayer(supply)
        try:
            f = next(f for f in supply.getFeatures() if f["AESI_MapLabel"] == "HW-3")
            i = supply.fields().lookupField("ExploElev")
            supply.dataProvider().changeAttributeValues({f.id(): {i: f["ExploElev"] + 30.0}})
            rows = [explo_row(self.pts), supply_row(supply)]
            m, _ = self.build(rows)
            by = by_label(m.hits)
            self.assertEqual(by["HW-3"].top_source, "dem")
            self.assertTrue(any(fl.startswith("ExploElev") and "ignored: 30.0 ft from LIDAR" in fl
                                for fl in by["HW-3"].flags), by["HW-3"].flags)
            self.assertIn("ignored", " ".join(by["MW-2"].flags))
            m, _ = self.build(rows, top_max_diff_ft=50.0)                       # one rule for every row
            by = by_label(m.hits)
            self.assertEqual((by["HW-3"].top_source, by["MW-2"].top_source), ("field", "dem"))   # MW-2: 300+ ft off
            m, _ = self.build(rows, top_mode="dem")
            self.assertTrue(all(h.top_source == "dem" for h in m.hits if h.label != "B-3"))
            m, _ = self.build(rows, td_label=False, depth_line=False)
            self.assertEqual(by_label(m.hits)["HW-1"].total_depth, 400.0)
        finally:
            self.prj.removeMapLayer(supply.id())

    def test_one_row_is_the_flat_shorthand(self):
        for kw in ({}, dict(types=["Boring", "CPT"]), dict(top_mode="field", label_field="")):
            flat = default_settings(self.prj, self.dem, self.pts, self.lines, **kw)
            rows = as_rows(flat)
            self.assertEqual(rows.points_layer_id, "")
            self.assertEqual(len(rows.point_layers), 1)
            a, b = build_section(flat, self.prj), build_section(rows, self.prj)
            self.assertEqual([dataclasses.asdict(h) for h in b.hits], [dataclasses.asdict(h) for h in a.hits], kw)
            for k in ("warnings", "beyond_ends", "near_count", "has_explorations", "points_name", "line_key"):
                self.assertEqual(getattr(b, k), getattr(a, k), (k, kw))
            self.assertEqual(len(a.point_layers), 1)
            self.assertEqual(a.point_layers[0].row, rows.point_layers[0])

    def test_one_row_with_screens_and_a_table_is_the_flat_shorthand(self):
        from tests.test_wells_surfaces import _wells_layer, _wl_table
        wells, table = _wells_layer(), _wl_table()
        self.prj.addMapLayers([wells, table])
        try:
            flat = default_settings(self.prj, self.dem, wells, self.lines, type_field="", screen_top_field="ScrTop",
                                    screen_bottom_field="ScrBot", wl_field="WL_Elev", wl_date_field="WL_Date",
                                    atd_field="ATD_Elev", wl_table_id=table.id(), wl_table_name_field="Name",
                                    wl_table_elev_field="Elev", wl_table_date_field="Date",
                                    wl_table_kind_field="Kind", wl_atd_values=["ATD"], wl_label="elev_date")
            a, b = build_section(flat, self.prj), build_section(as_rows(flat), self.prj)
            self.assertTrue(any(h.water_levels for h in a.hits))
            self.assertEqual([dataclasses.asdict(h) for h in b.hits], [dataclasses.asdict(h) for h in a.hits])
            self.assertEqual(b.warnings, a.warnings)
        finally:
            self.prj.removeMapLayers([wells.id(), table.id()])

    def test_a_table_shared_by_two_rows_is_read_once(self):
        from tests.test_wells_surfaces import _wells_layer, _wl_table
        wells, table = _wells_layer(), _wl_table()
        self.prj.addMapLayers([wells, table])
        try:
            keys = dict(label_field="ExploName", depth_field="ExploDepth", wl_field="WL_Elev",
                        wl_table_id=table.id(), wl_table_name_field="Name", wl_table_elev_field="Elev",
                        wl_table_date_field="Date", wl_table_kind_field="Kind")
            rows = [point_row(wells, **keys), point_row(wells, name="Wells again", **keys)]
            with mock.patch.object(B, "read_wl_table", wraps=E.read_wl_table) as read:
                m, _ = self.build(rows)
            self.assertEqual(read.call_count, 1)
            w1 = [h for h in m.hits if h.label == "W-1"]
            self.assertEqual(len(w1), 2)
            self.assertEqual(w1[0].water_levels, w1[1].water_levels)
            self.assertIn(512.0, [w.elev for w in w1[0].water_levels])         # from the table
            rows[1] = point_row(wells, name="Wells again", **dict(keys, wl_table_kind_field=""))
            with mock.patch.object(B, "read_wl_table", wraps=E.read_wl_table) as read:
                self.build(rows)
            self.assertEqual(read.call_count, 2)                                # another reading of it
            with mock.patch.object(B, "read_wl_table", wraps=E.read_wl_table) as read:
                self.build(rows, screens=False)
            self.assertEqual(read.call_count, 0)
        finally:
            self.prj.removeMapLayers([wells.id(), table.id()])

    def test_rows_left_out(self):
        rows = [explo_row(self.pts), others_row(self.others, visible=False), point_row(layer_id="", name="Later"),
                supply_row(self.supply, visible=False)]
        m, _ = self.build(rows)
        self.assertEqual([h.label for h in m.hits], PLOTTED)
        self.assertEqual([i.on for i in m.point_layers], [True, False, False, False])
        self.assertEqual([i.name for i in m.point_layers], ["Explorations", "Explorations by others", "Later",
                                                            "Supply wells"])
        self.assertEqual(m.point_layers[2].layer_name, "")
        self.assertEqual(m.beyond_ends, ["B-pre", "B-post"])                   # one row on: plain labels
        m, _ = self.build([point_row(layer_id=""), others_row(self.others, visible=False)])
        self.assertEqual(m.hits, [])
        self.assertFalse(m.has_explorations)
        self.assertEqual(m.points_name, "")
        self.assertIn(NO_POINTS, m.warnings)
        self.assertFalse(any(w.startswith("No explorations within") for w in m.warnings))
        self.assertEqual([i.name for i in m.point_layers], ["row 1", "Explorations by others"])

    def test_a_missing_row_layer_is_an_error_naming_the_row(self):
        def message(rows):
            with self.assertRaises(SectionError) as cm:
                self.build(rows)
            return str(cm.exception)
        text = message([explo_row(self.pts), point_row(layer_id="gone", name="By others")])
        self.assertEqual(text, "The explorations (points) layer of “By others” is no longer in the project. "
                               "Choose it again, untick its row or remove it.")
        text = message([explo_row(self.pts), point_row(layer_id="gone")])
        self.assertIn("of “row 2”", text)
        text = message([point_row(layer_id="gone")])
        self.assertTrue(text.startswith("The explorations (points) layer is no longer in the project."), text)
        self.assertIn("of “row 1”", message([point_row(layer_id=self.dem.id()), explo_row(self.pts)]))   # a raster
        m, _ = self.build([explo_row(self.pts), point_row(layer_id="gone", visible=False)])   # unticked: fine
        self.assertEqual([h.label for h in m.hits], PLOTTED)
        self.assertEqual(m.point_layers[1].name, "row 2")
        # a row's field error is prefixed with the row's name when several rows are ticked
        text = message([explo_row(self.pts), others_row(self.others, label_field="Nope")])
        self.assertTrue(text.startswith("Explorations by others: The label field “Nope”"), text)
        text = message([others_row(self.others, label_field="Nope")])
        self.assertTrue(text.startswith("The label field “Nope”"), text)
        text = message([explo_row(self.pts), others_row(self.others, name="Others", depth_field="Nope")])
        self.assertTrue(text.startswith("Others: The total depth field “Nope”"), text)

    def test_looks_and_range_are_stamped_on_each_hit(self):
        rows = [explo_row(self.pts), others_row(self.others, look="gray", name="By others"),
                supply_row(self.supply, look="color", color="#123456", in_range=False)]
        self.supply.setRenderer(single_renderer("#123456"))       # (0.3.4) Color: the colour of the layer's style
        m, _ = self.build(rows)
        for h in m.hits:
            want = [("black", "", True), ("gray", LOOK_GRAY, True), ("color", "#123456", False)][h.layer_index]
            self.assertEqual((h.look, h.color, h.in_range), want, h.label)
            self.assertEqual(h.layer_name, ["Explorations", "By others", "Supply wells"][h.layer_index])
        self.assertEqual([(i.look, i.color, i.in_range) for i in m.point_layers],
                         [("black", "", True), ("gray", LOOK_GRAY, True), ("color", "", False)])
        self.assertEqual(m.point_layers[2].style.kind, "single")
        self.assertEqual(m.point_layers[1].layer_name, "Explorations by others")

    def test_ground_only(self):
        m, _ = self.build([])
        self.assertEqual((m.hits, m.left_off, m.point_layers, m.other_points), ([], [], [], []))
        self.assertFalse(m.has_explorations)
        self.assertFalse(m.has_points)
        self.assertIn(NO_POINTS, m.warnings)


class LeftOff(unittest.TestCase):
    """hidden_points: explorations he left off one section line (the Plotted explorations list)."""

    @classmethod
    def setUpClass(cls):
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        cls.others = make_others_layer()
        cls.prj.addMapLayer(cls.others)
        cls.fid = {f["ExploName"]: f.id() for f in cls.pts.getFeatures()}
        cls.ofid = {f["ExploName"]: f.id() for f in cls.others.getFeatures()}

    def build(self, rows, hidden, **kw):
        s = rows_settings(self.prj, self.dem, self.lines, rows, hidden_points=hidden, **kw)
        return build_section(s, self.prj), s

    def test_an_entry_moves_the_hit_to_left_off(self):
        lk = f"{self.lines.id()}#{next(self.lines.getFeatures()).id()}"
        hidden = [hidden_key(lk, self.pts.id(), self.fid["MW-2"]), hidden_key(lk, self.pts.id(), self.fid["B-1"])]
        m, s = self.build([explo_row(self.pts)], hidden)
        self.assertEqual(line_key(s), lk)
        self.assertEqual([h.label for h in m.hits], [n for n in PLOTTED if n not in ("MW-2", "B-1")])
        self.assertEqual([h.label for h in m.left_off], ["B-1", "MW-2"])          # sorted like hits
        self.assertFalse(any(w.startswith("MW-2:") for w in m.warnings))         # its flags are not reported
        self.assertTrue(any(w.startswith("B-3:") for w in m.warnings))
        self.assertEqual((m.point_layers[0].plotted, m.point_layers[0].left_off), (5, 2))
        self.assertEqual(m.left_off[1].layer_id, self.pts.id())
        # another line key does not apply
        m2, _ = self.build([explo_row(self.pts)], [hidden_key("drawn", self.pts.id(), self.fid["MW-2"]),
                                                    hidden_key(lk + "0", self.pts.id(), self.fid["MW-2"])])
        self.assertEqual([h.label for h in m2.hits], PLOTTED)
        self.assertEqual(m2.left_off, [])
        # the same entries for a drawn line apply once the line is drawn
        from tests.test_build import _wkt
        from tests.fixtures import LINE
        m3, s3 = self.build([explo_row(self.pts)], [hidden_key("drawn", self.pts.id(), self.fid["MW-2"])],
                            line_layer_id="", line_fid=None, line_wkt=_wkt(LINE), line_crs_authid=CRS)
        self.assertEqual((m3.line_key, [h.label for h in m3.left_off]), ("drawn", ["MW-2"]))

    def test_keyed_by_layer(self):
        lk = f"{self.lines.id()}#{next(self.lines.getFeatures()).id()}"
        rows = [explo_row(self.pts), others_row(self.others), explo_row(self.pts, name="Again")]
        m, _ = self.build(rows, [hidden_key(lk, self.others.id(), self.ofid["B-2x"]),
                                 hidden_key(lk, self.pts.id(), self.fid["B-3"])])
        self.assertIn("B-2", [h.label for h in m.hits])                        # B-2x's neighbour stays
        self.assertEqual([(h.label, h.layer_index) for h in m.left_off], [("B-2x", 1), ("B-3", 0), ("B-3", 2)])
        self.assertEqual([i.left_off for i in m.point_layers], [1, 1, 1])
        self.assertEqual([(h.station, h.layer_index, h.label) for h in m.left_off],
                         sorted((h.station, h.layer_index, h.label) for h in m.left_off))

    def test_all_left_off(self):
        lk = f"{self.lines.id()}#{next(self.lines.getFeatures()).id()}"
        m, _ = self.build([explo_row(self.pts)], [hidden_key(lk, self.pts.id(), self.fid[n]) for n in PLOTTED])
        self.assertEqual(m.hits, [])
        self.assertEqual(len(m.left_off), len(PLOTTED))
        self.assertIn(f"Every exploration within {TOLERANCE:g} ft of the line is left off (see Plotted "
                      "explorations).", m.warnings)
        self.assertFalse(any(w.startswith("No explorations within") for w in m.warnings))
        self.assertTrue(m.has_explorations)
        # an entry for an exploration not chosen is inert
        m, _ = self.build([explo_row(self.pts, types=["Boring"])], [hidden_key(lk, self.pts.id(), self.fid["MW-1"])])
        self.assertEqual([h.label for h in m.hits], ["B-1", "B-2", "B-3"])
        self.assertEqual(m.left_off, [])


class Types(unittest.TestCase):
    """`types` with "" (the NULL-or-empty value, "(no value)" in the panel)."""

    @classmethod
    def setUpClass(cls):
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        cls.others = make_others_layer()
        cls.gpkg = write_gpkg(make_others_layer(), "others_gpkg")
        cls.prj.addMapLayers([cls.others, cls.gpkg])

    def labels(self, layer, types, **kw):
        s = rows_settings(self.prj, self.dem, self.lines, [others_row(layer, types=types, **kw)])
        return [h.label for h in build_section(s, self.prj).hits]

    def test_types(self):
        for layer in (self.others, self.gpkg):
            with self.subTest(layer=layer.providerType()):
                self.assertEqual(self.labels(layer, [""]), ["O-2", "O-3"])     # NULL and '' only
                self.assertEqual(self.labels(layer, ["Boring", ""]), ["O-1", "O-2", "B-2x", "O-3"])
                self.assertEqual(self.labels(layer, ["Boring"]), ["O-1", "B-2x"])
                self.assertEqual(self.labels(layer, []), ["O-1", "O-2", "B-2x", "O-4", "O-3"])
                self.assertEqual(self.labels(layer, [NO_TYPES]), [])
                self.assertEqual(self.labels(layer, ["", NO_TYPES]), ["O-2", "O-3"])

    def test_filter_text(self):
        i = self.others.fields().lookupField("ExploType_resolved")
        self.assertEqual(E._type_filter(self.others, i, []), "")
        self.assertEqual(E._type_filter(self.others, -1, ["Boring"]), "")
        self.assertEqual(E._type_filter(self.others, i, ["Boring", "CPT"]),
                         "\"ExploType_resolved\" IN ('Boring', 'CPT')")                # unchanged without ""
        self.assertEqual(E._type_filter(self.others, i, ["Boring", ""]),
                         "\"ExploType_resolved\" IN ('Boring') OR \"ExploType_resolved\" IS NULL OR "
                         "\"ExploType_resolved\" = ''")
        self.assertEqual(E._type_filter(self.others, i, [""]),
                         "\"ExploType_resolved\" IS NULL OR \"ExploType_resolved\" = ''")
        d = self.pts.fields().lookupField("ExploDepth")                         # a numeric "type" field
        self.assertEqual(E._type_filter(self.pts, d, ["30", "45.0"]), "\"ExploDepth\" IN (30.0, 45.0)")
        self.assertEqual(E._type_filter(self.pts, d, ["30", ""]), "\"ExploDepth\" IN (30.0) OR \"ExploDepth\" IS NULL")
        self.assertEqual(E._type_filter(self.pts, d, [""]), "\"ExploDepth\" IS NULL")

    def test_numeric_type_field_with_no_value(self):
        s = rows_settings(self.prj, self.dem, self.lines,
                          [explo_row(self.pts, type_field="ExploDepth", types=["30", ""])])
        m = build_section(s, self.prj)
        self.assertEqual([h.label for h in m.hits], ["B-1", "B-3"])              # B-3 has no depth (NULL)
        self.assertEqual(sorted(m.beyond_ends), ["B-post", "B-pre"])
        crs = QgsCoordinateReferenceSystem(CRS)
        line = resolve_line(s, self.prj, crs)
        far = E.nearest_distance_ft(line, self.pts, layer_view(s, layer_rows(s)[0]), crs, FTUS, self.prj)
        self.assertLess(far, TOLERANCE)


class Dates(unittest.TestCase):
    def test_epoch_milliseconds(self):
        for value, want in ((1612281600000, "2/2/2021"), (1733702400000, "12/9/2024"), (824745600000, "2/19/1996"),
                            (1773730800000, "3/17/2026"), (-367002000000, "5/16/1958"), (-2209132800000, ""),
                            (1612281600000.0, "2/2/2021"), (2021, "2021"), (20210202, "20210202"),
                            (1000000000, "1/12/1970"), (999999999, "999999999"), (2021.0, "2021"),
                            (1612281600000.5, "1612281600000.5"), (10 ** 20, str(10 ** 20)), (True, "True"),
                            (None, ""), ("1612281600000", "1612281600000")):
            self.assertEqual(E.date_text(value, epoch_ms=True), want, value)
        self.assertEqual(E.date_text(1612281600000), "1612281600000")         # not a number field: as written
        self.assertEqual(E.date_text(1612281600000, True), "2/2/2021")

    def test_through_find_explorations(self):
        prj, dem, pts, lines = load_project()
        supply = make_supply_layer()
        gpkg = write_gpkg(make_supply_layer(), "supply_gpkg")
        prj.addMapLayers([supply, gpkg])
        for layer in (supply, gpkg):
            with self.subTest(layer=layer.providerType()):
                date_i = layer.fields().lookupField("ExploDate")
                self.assertTrue(layer.fields().at(date_i).isNumeric())
                s = rows_settings(prj, dem, lines, [supply_row(layer)])          # ATD elevations, dated
                by = by_label(build_section(s, prj).hits)
                self.assertEqual([(w.kind, w.date) for w in by["HW-1"].water_levels], [("atd", "2/2/2021")])
                self.assertEqual([(w.kind, w.date) for w in by["HW-3"].water_levels], [("atd", "5/16/1958")])
                self.assertEqual(by["HW-2"].water_levels, [])
                row = supply_row(layer, atd_field="", wl_field="DepthToGW_ATD", wl_values="depth",
                                 wl_date_field="ExploDate")                       # a measured depth, dated
                by = by_label(build_section(rows_settings(prj, dem, lines, [row]), prj).hits)
                hw1 = by["HW-1"]
                self.assertEqual([(w.kind, w.date) for w in hw1.water_levels], [("measured", "2/2/2021")])
                self.assertAlmostEqual(hw1.water_levels[0].elev, hw1.top - 30.0, delta=1e-9)

    def test_through_the_table(self):
        prj, dem, pts, lines = load_project()
        t = QgsVectorLayer("None", "levels", "memory")
        t.dataProvider().addAttributes([QgsField("Name", QMetaType.Type.QString),
                                        QgsField("Elev", QMetaType.Type.Double),
                                        QgsField("Date", QMetaType.Type.LongLong)])
        t.updateFields()
        x, y = point_at(300.0, 40.0)
        feats = []
        for name, elev, date in (("B-1", plane_z(x, y) - 10.0, 1733702400000), ("B-1", plane_z(x, y) - 12.0, 2021)):
            f = QgsFeature(t.fields())
            f.setAttributes([name, elev, date])
            feats.append(f)
        t.dataProvider().addFeatures(feats)
        prj.addMapLayer(t)
        s = rows_settings(prj, dem, lines, [explo_row(pts, wl_table_id=t.id(), wl_table_name_field="Name",
                                                      wl_table_elev_field="Elev", wl_table_date_field="Date")])
        b1 = by_label(build_section(s, prj).hits)["B-1"]
        self.assertEqual([w.date for w in b1.water_levels], ["12/9/2024", "2021"])


class HoverPerRow(unittest.TestCase):
    """hit_cells reads the top and water-level fields of the hit's own row (core/hover.py, 3.8)."""

    def hit(self, **kw):
        base = dict(fid=4, label="MW-4", type_value="Monitoring well", x=0.0, y=0.0, station=702.3, offset=9.0,
                    side="R", direction="E", ground_at_station=660.0, ground_at_point=660.0, top=660.4,
                    top_source="field", bottom=638.9, bottom_source="depth", total_depth=21.5)
        base.update(kw)
        return Hit(**base)

    def test_rows_only_settings(self):
        s = Settings(point_layers=[point_row(layer_id="L0", top_field="ExploElev", wl_field="WL"),
                                   point_row(layer_id="L1", top_field="TopZ")])
        self.assertEqual(s.top_field, "")                                        # flat keys at their defaults
        cells = H.hit_cells(self.hit(layer_index=0, layer_id="L0"), s)
        self.assertIn(("Top", "660.4 ft", "ExploElev"), cells)                  # not "table"
        self.assertIn(("Water level", "—", "none"), cells)                      # that row reads levels
        cells = H.hit_cells(self.hit(layer_index=1, layer_id="L1"), s)
        self.assertIn(("Top", "660.4 ft", "TopZ"), cells)
        self.assertNotIn("Water level", [c[0] for c in cells])
        self.assertEqual(H.hit_cells(self.hit(layer_index=0, layer_id="L0"), dataclasses.replace(s, screens=False))
                         [-1][0], "Total depth")                                 # screens are shared

    def test_flat_settings_unchanged(self):
        for s in (Settings(top_field="ExploElev", wl_field="WL"),
                  Settings(points_layer_id="P", top_field="ExploElev", wl_field="WL")):
            cells = H.hit_cells(self.hit(), s)
            self.assertEqual(cells, [("Monitoring well", "MW-4", ""), ("From A", "702 ft", "9 ft right"),
                                     ("Top", "660.4 ft", "ExploElev"), ("Total depth", "21.5 ft", "bottom 638.9"),
                                     ("Water level", "—", "none")])
        cells = H.hit_cells(self.hit(), Settings(points_layer_id="P"))
        self.assertIn(("Top", "660.4 ft", "table"), cells)
        self.assertNotIn("Water level", [c[0] for c in cells])


# ===================================================================================================== budgets
@timing_test
class Speed(unittest.TestCase):
    """The budgets of 3.7 on the dense fixture (32,000 points in a GeoPackage with an R-tree), 5x headroom."""

    @classmethod
    def setUpClass(cls):
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        t = time.perf_counter()
        cls.dense = make_dense_layer()
        cls.made = time.perf_counter() - t
        cls.others = make_others_layer()
        cls.supply = make_supply_layer()
        cls.prj.addMapLayers([cls.dense, cls.others, cls.supply])

    def dense_row(self, **kw):
        return point_row(self.dense, label_field="ExploName", type_field="ExploType_resolved",
                         top_field="ExploElev", depth_field="ExploDepth", **kw)

    def test_dense_fixture(self):
        self.assertEqual(self.dense.featureCount(), 32_000)
        self.assertEqual(self.dense.providerType(), "ogr")
        self.assertEqual([self.dense.fields().at(i).name() for i in self.dense.primaryKeyAttributes()], ["id"])
        again = make_dense_layer()                                              # cached: opened again, not made
        self.assertEqual(again.source(), self.dense.source())
        # (FIX 0.3.3) one file every run reuses, in the system temp's xsec_cache, never a copy in this run's folder
        # (one was left behind whenever OGR still held it at exit)
        import os
        from tests.fixtures import RUN_TMP
        path = os.path.normcase(os.path.abspath(self.dense.source().split("|")[0]))
        self.assertEqual(os.path.basename(os.path.dirname(path)), "xsec_cache")
        self.assertFalse(path.startswith(os.path.normcase(os.path.abspath(RUN_TMP))))
        self.assertEqual(os.path.dirname(os.path.dirname(path)), os.path.normcase(os.path.dirname(os.path.abspath(RUN_TMP))))
        print(f"\n  dense fixture made/opened in {self.made:.2f} s")

    def test_find_explorations_budget(self):
        s = rows_settings(self.prj, self.dem, self.lines, [self.dense_row()])
        ls = layer_view(s, layer_rows(s)[0])
        crs = QgsCoordinateReferenceSystem(CRS)
        line = resolve_line(s, self.prj, crs)
        sampler = raster_sampler(self.dem, 1, crs, 1.0)
        ground = ground_profile(line, sampler, CELL * FTUS, FTUS)
        t = time.perf_counter()
        hits, beyond, near = E.find_explorations(line, self.dense, ls, crs, sampler, FTUS, self.prj, ground=ground)
        dt = time.perf_counter() - t
        self.assertEqual(len(hits), 60)
        self.assertEqual((beyond, near), ([], 0))
        self.assertLessEqual(dt, budget(0.5), f"find_explorations over 32,000 points took {dt:.3f} s")
        print(f"\n  find_explorations, 32,000 points: {dt:.3f} s")

    def test_three_row_build_budget(self):
        s = rows_settings(self.prj, self.dem, self.lines,
                          [self.dense_row(), others_row(self.others), supply_row(self.supply, in_range=False)])
        t = time.perf_counter()
        m = build_section(s, self.prj)
        dt = time.perf_counter() - t
        self.assertEqual([i.plotted for i in m.point_layers], [60, 5, 4])
        self.assertLessEqual(dt, budget(1.5), f"3-row build took {dt:.3f} s")
        print(f"\n  3-row build (dense, others, supply): {dt:.3f} s")


if __name__ == "__main__":
    unittest.main()
