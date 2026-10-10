"""0.3.6 Other features, the core part: line and polygon layers as rows of Settings.other_points (build spec sections 3
and 4, tests 8.3). A line row draws its symbol wherever the section line crosses one of its lines (core/others.py
find_crossings: each crossing an OtherPoint of kind "crossing", placed by the point rows' rules); a polygon row marks
each stretch of the section line inside one of its polygons (find_area_pieces: model.other_areas, drawn as brackets).
The settings: four new row keys with defaults, no version step; a 0.3.5 row loads as itself (a point row)."""
import json
import time
import unittest

from tests.fixtures import (CRS, TOLERANCE, area_row, budget, line_length, load_project,
                            make_areas_layer, make_seeps_layer, make_streams_layer, plane_z, point_at, point_row,
                            seep_row, start_app, stream_row, timing_test)
from tests.test_units import FTUS

APP = start_app()

from qgis.core import (QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProject,  # noqa: E402
                       QgsVectorLayer)
from qgis.PyQt.QtCore import QMetaType  # noqa: E402

from xsections.core import hover as Hv  # noqa: E402
from xsections.core import others as O  # noqa: E402
from xsections.core.build import build_section  # noqa: E402
from xsections.core.model import (AREA_COLOR_DEFAULT, AREA_EDGES, AREA_PLACES, AREA_STYLES,  # noqa: E402
                                  DEFAULT_SHAPE, FEATURE_KINDS, NO_POINTS, NO_TYPES, OTHER_POINT_DEFAULTS,
                                  SETTINGS_VERSION, AreaPiece, Hit, OtherPoint, SectionError, Settings,
                                  clean_other_point, feature_row)
from xsections.core.section import raster_sampler, resolve_line, vertex_stations  # noqa: E402
from xsections.ui import settings_store  # noqa: E402

# a stored row of 0.3.5, exactly as it saved it (its 12 keys)
ROW_035 = {"layer_id": "seeps1", "visible": True, "name": "Seeps", "label_field": "Name", "type_field": "Type",
           "types": ["Seep", ""], "shape": "diamond", "color": "#aa3300", "size": 9.5, "elev": "field",
           "elev_field": "Elev_ft", "elev_empty": "lidar"}
NEW_KEYS = {"kind": "point", "bracket": "inside", "bracket_style": "solid", "edges": "off"}


def L_ft():
    return line_length() * FTUS


# ----------------------------------------------------------------------------- settings and the model
class RowKeys(unittest.TestCase):
    def test_new_keys_their_defaults_and_order(self):
        self.assertEqual(list(OTHER_POINT_DEFAULTS),
                         ["layer_id", "visible", "name", "label_field", "type_field", "types", "shape", "color",
                          "size", "elev", "elev_field", "elev_empty", "kind", "bracket", "bracket_style", "edges"])
        self.assertEqual({k: OTHER_POINT_DEFAULTS[k] for k in NEW_KEYS}, NEW_KEYS)
        self.assertEqual(FEATURE_KINDS, ("point", "line", "polygon"))
        self.assertEqual((AREA_PLACES, AREA_EDGES, AREA_STYLES), (("inside", "above"), ("off", "ground", "full"),
                                                                    ("solid", "dash")))
        self.assertEqual(AREA_COLOR_DEFAULT, "#7a4fb0")
        self.assertEqual(DEFAULT_SHAPE, {"point": "asterisk", "line": "stream", "polygon": "asterisk"})
        self.assertEqual(SETTINGS_VERSION, 7)                                # no version step (spec 3.2)

    def test_cleaning(self):
        d = clean_other_point({"kind": "banana", "bracket": "middle", "bracket_style": "dot", "edges": "half"})
        self.assertEqual({k: d[k] for k in NEW_KEYS}, NEW_KEYS)
        for kind, shape in (("point", "asterisk"), ("line", "stream"), ("polygon", "asterisk")):
            self.assertEqual(clean_other_point({"kind": kind, "shape": "hexagon"})["shape"], shape, kind)
            self.assertEqual(clean_other_point({"kind": kind, "shape": "spring"})["shape"], "spring", kind)
        d = clean_other_point({"kind": "polygon", "bracket": "above", "bracket_style": "dash", "edges": "full"})
        self.assertEqual((d["kind"], d["bracket"], d["bracket_style"], d["edges"]), ("polygon", "above", "dash", "full"))
        self.assertEqual(clean_other_point({"kind": 3})["kind"], "point")      # a wrong kind of value

    def test_feature_row(self):
        point = dict(layer_id="", visible=True, name="", label_field="", type_field="", types=[], shape="asterisk",
                     color="#1f6fb2", size=7.0, elev="line", elev_field="", elev_empty="line", kind="point",
                     bracket="inside", bracket_style="solid", edges="off")
        self.assertEqual(feature_row(), point)
        self.assertEqual(feature_row("point"), point)
        self.assertEqual(feature_row("line"), dict(point, shape="stream", kind="line"))
        self.assertEqual(feature_row("polygon"), dict(point, kind="polygon", color="#7a4fb0"))
        self.assertEqual(feature_row("polygon", layer_id="x", bracket="above", color="#123ABC"),
                         dict(point, kind="polygon", color="#123abc", layer_id="x", bracket="above"))
        self.assertEqual(feature_row("cloud")["kind"], "point")
        self.assertEqual(list(feature_row("line")), list(OTHER_POINT_DEFAULTS))

    def test_a_035_row_loads_as_itself_plus_the_defaults(self):
        expected = dict(ROW_035, **NEW_KEYS)
        data = json.loads(Settings().to_json())
        data["other_points"] = [dict(ROW_035)]
        data["version"] = 7
        s = Settings.from_json(json.dumps(data))
        self.assertEqual(s.other_points, [expected])
        self.assertEqual(list(s.other_points[0]), list(OTHER_POINT_DEFAULTS))
        prj = QgsProject.instance()
        prj.clear()
        self.addCleanup(prj.clear)
        prj.writeEntry(settings_store.SCOPE, settings_store.KEY, json.dumps(data))
        self.assertEqual(settings_store.load(prj).other_points, [expected])

    def test_a_036_row_round_trips(self):
        rows = [area_row(layer_id="a", name="Sites", label_field="Name", bracket="above", bracket_style="dash",
                         edges="full", color="#2e7d32"),
                stream_row(layer_id="s", shape="spring", elev="lidar"), seep_row(layer_id="p", shape="well")]
        s = Settings(other_points=rows)
        self.assertEqual(Settings.from_json(s.to_json()).other_points, rows)
        prj = QgsProject.instance()
        prj.clear()
        self.addCleanup(prj.clear)
        self.assertTrue(settings_store.save(prj, s))
        self.assertEqual(settings_store.load(prj).other_points, rows)
        self.assertFalse(settings_store.save(prj, settings_store.load(prj)))   # unchanged: not written again

    def test_model_fields(self):
        p = OtherPoint(fid=1, label="a", type_value="", x=0.0, y=0.0, station=1.0, offset=0.0, side="L",
                       direction="", ground_at_station=1.0, ground_at_point=1.0, z=1.0, how="line")
        self.assertEqual(p.kind, "point")
        a = AreaPiece(fid=1, label="", type_value="", start=1.0, end=2.0)
        self.assertEqual((a.open_start, a.open_end, a.layer_index, a.layer_id, a.layer_name), (False, False, 0, "", ""))


# ----------------------------------------------------------------------------- the core
def _line_layer(name, rows, crs=CRS):
    """A memory MultiLineString layer: rows (Name, Type, Bed_ft, [part, ...]) with parts of (station, offset)."""
    lyr = QgsVectorLayer(f"MultiLineString?crs={crs}", name, "memory")
    lyr.dataProvider().addAttributes([QgsField("Name", QMetaType.Type.QString), QgsField("Type", QMetaType.Type.QString),
                                      QgsField("Bed_ft", QMetaType.Type.Double)])
    lyr.updateFields()
    feats = []
    for n, typ, bed, parts in rows:
        f = QgsFeature(lyr.fields())
        f.setAttributes([n, typ, bed])
        f.setGeometry(QgsGeometry.fromMultiPolylineXY([[QgsPointXY(*point_at(st, off)) for st, off in part]
                                                       for part in parts]))
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    return lyr


def _polygon_layer(name, rows, crs=CRS):
    """A memory Polygon layer: rows (Name, Type, [ring, ...]) with rings of (station, offset)."""
    lyr = QgsVectorLayer(f"Polygon?crs={crs}", name, "memory")
    lyr.dataProvider().addAttributes([QgsField("Name", QMetaType.Type.QString), QgsField("Type", QMetaType.Type.QString)])
    lyr.updateFields()
    feats = []
    for n, typ, rings in rows:
        f = QgsFeature(lyr.fields())
        f.setAttributes([n, typ])
        f.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(*point_at(st, off)) for st, off in r] for r in rings]))
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    return lyr


class _Project(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        cls.streams, cls.areas, cls.seeps = make_streams_layer(), make_areas_layer(), make_seeps_layer()
        cls.prj.addMapLayers([cls.streams, cls.areas, cls.seeps])

    def settings(self, others, rows=(), **kw):
        s = Settings(line_layer_id=self.lines.id(), line_fid=next(self.lines.getFeatures()).id(),
                     dem_layer_id=self.dem.id(), tolerance_ft=TOLERANCE, point_layers=list(rows),
                     other_points=list(others))
        for k, v in kw.items():
            setattr(s, k, v)
        return s

    def build(self, others, rows=(), **kw):
        return build_section(self.settings(others, rows, **kw), self.prj)

    def add(self, layer):
        self.prj.addMapLayer(layer)
        self.addCleanup(self.prj.removeMapLayer, layer.id())
        return layer


class KindsAndLayers(_Project):
    def test_feature_kind_and_feature_layer(self):
        table = self.add(QgsVectorLayer("None?field=name:string", "Lab table", "memory"))
        for layer, kind in ((self.seeps, "point"), (self.streams, "line"), (self.areas, "polygon"), (table, ""),
                            (None, ""), (self.dem, "")):
            self.assertEqual(O.feature_kind(layer), kind, layer)
        self.assertIs(O.feature_layer(self.streams.id(), self.prj), self.streams)
        self.assertIs(O.feature_layer(self.areas.id()), self.areas)                 # the project instance
        self.assertIs(O.feature_layer(self.seeps.id(), self.prj), self.seeps)
        self.assertIsNone(O.feature_layer(table.id(), self.prj))
        self.assertIsNone(O.feature_layer(self.dem.id(), self.prj))
        self.assertIsNone(O.feature_layer("", self.prj))
        gone = make_streams_layer(name="Gone")
        self.prj.addMapLayer(gone)
        gid = gone.id()
        self.prj.removeMapLayer(gid)
        self.assertIsNone(O.feature_layer(gid, self.prj))


class Crossings(_Project):
    def crossings(self, **kw):
        m = self.build([stream_row(self.streams, label_field="Name", **kw)])
        return m.other_points, m

    def test_where_the_lines_cross(self):
        pts, m = self.crossings()
        self.assertEqual([p.label for p in pts], ["Clover Cr.", "Clover Cr.", "Ditch 4", "Canal"])   # Dry run: none
        line = resolve_line(self.settings([]), self.prj, self.dem.crs())
        for p, st in zip(pts, (900.0, 1500.0, 2500.0, 3750.0)):
            self.assertIsInstance(p, OtherPoint)
            self.assertAlmostEqual(p.station, st * FTUS, delta=0.01, msg=p.label)
            self.assertEqual((p.kind, p.offset, p.side, p.direction), ("crossing", 0.0, "", ""), p.label)
            self.assertLess(line.distance(QgsGeometry.fromPointXY(QgsPointXY(p.x, p.y))), 1e-6, p.label)  # on it
            self.assertEqual((p.layer_index, p.layer_id, p.layer_name), (0, self.streams.id(), "Streams"))
        keys = [(p.station, p.label) for p in pts]
        self.assertEqual(keys, sorted(keys))
        canal = pts[3]
        self.assertEqual(canal.flags, ["runs along the section line for 300 ft"])
        self.assertIn("Canal: runs along the section line for 300 ft", m.warnings)
        self.assertEqual([p.flags for p in pts[:3]], [[], [], []])
        info = m.other_layers[0]
        self.assertEqual((info.kind, info.on, info.plotted, info.near, info.beyond, info.no_elevation),
                         ("line", True, 4, 0, [], []))
        self.assertEqual(m.hits, [])                                           # the points CSV writes hits only

    def test_placed_as_points_are(self):
        pts, m = self.crossings()
        for p in pts:                                                          # on the ground line
            self.assertEqual((p.how, p.fell_back, p.field_value), ("line", False, None))
            self.assertEqual((p.z, p.ground_at_station), (m.ground.z_at(p.station),) * 2)
            self.assertAlmostEqual(p.ground_at_point, plane_z(p.x, p.y), delta=0.01)
        pts, _ = self.crossings(elev="lidar")
        for p in pts:
            self.assertEqual((p.how, p.fell_back), ("lidar", False))
            self.assertAlmostEqual(p.z, plane_z(p.x, p.y), delta=0.01)
        pts, m = self.crossings(elev="field", elev_field="Bed_ft")             # empty: on the ground line
        self.assertEqual([(p.label, p.how, p.z, p.fell_back) for p in pts[:2]],
                         [("Clover Cr.", "field", 497.0, False)] * 2)
        self.assertEqual([(p.how, p.fell_back, p.z) for p in pts[2:]],
                         [("line", True, p.ground_at_station) for p in pts[2:]])
        pts, _ = self.crossings(elev="field", elev_field="Bed_ft", elev_empty="lidar")
        self.assertEqual([(p.how, p.fell_back) for p in pts[2:]], [("lidar", True)] * 2)
        pts, m = self.crossings(elev="field", elev_field="Bed_ft", elev_empty="off")
        self.assertEqual([p.label for p in pts], ["Clover Cr.", "Clover Cr."])
        self.assertEqual(sorted(m.other_layers[0].no_elevation), ["Canal", "Ditch 4"])
        self.assertEqual(m.other_layers[0].plotted, 2)

    def test_types_and_labels(self):
        pts, _ = self.crossings(type_field="Type", types=["Ditch"])
        self.assertEqual([(p.label, p.type_value) for p in pts], [("Ditch 4", "Ditch")])
        pts, m = self.crossings(type_field="Type", types=[NO_TYPES])
        self.assertEqual((pts, m.other_layers[0].plotted), ([], 0))
        pts, _ = self.crossings(type_field="Type")
        self.assertEqual([p.type_value for p in pts], ["Perennial", "Perennial", "Ditch", "Canal"])
        lyr = self.add(_line_layer("Ditches", [("", "Ditch", None, [[(1100.0, 50.0), (1100.0, -50.0)]]),
                                               (None, "Ditch", None, [[(1300.0, 50.0), (1300.0, -50.0)]])]))
        m = self.build([stream_row(lyr, label_field="Name")])
        fids = sorted(f.id() for f in lyr.getFeatures())
        self.assertEqual([p.label for p in m.other_points], [f"#{fids[0]}", f"#{fids[1]}"])
        m = self.build([stream_row(lyr)])                                      # no label field: the fid
        self.assertEqual([p.label for p in m.other_points], [f"#{fids[0]}", f"#{fids[1]}"])

    def test_a_multi_line_feature_and_one_crossing_twice(self):
        lyr = self.add(_line_layer("Multi", [("Twin", "Creek", None, [[(500.0, 100.0), (500.0, -100.0)],
                                                                      [(700.0, 100.0), (700.0, -100.0)]]),
                                             ("Zigzag", "Creek", None, [[(1000.0, 50.0), (1050.0, -50.0),
                                                                         (1100.0, 50.0), (1150.0, -50.0)]])]))
        m = self.build([stream_row(lyr, label_field="Name")])
        got = [(p.label, round(p.station / FTUS, 3)) for p in m.other_points]
        self.assertEqual(got, [("Twin", 500.0), ("Twin", 700.0), ("Zigzag", 1025.0), ("Zigzag", 1075.0),
                               ("Zigzag", 1125.0)])

    def test_a_missing_field_is_an_error_naming_the_row(self):
        for kw, field in ((dict(label_field="Nope"), "label"), (dict(type_field="Nope"), "type"),
                          (dict(elev="field", elev_field="Nope"), "elevation")):
            with self.assertRaises(SectionError) as cm:
                self.build([stream_row(self.streams, **dict(dict(label_field="Name"), **kw))])
            self.assertEqual(str(cm.exception),
                             f"Streams: The {field} field “Nope” is not in Streams. Choose another field.")

    def test_a_layer_in_another_crs(self):
        geo = self.add(make_streams_layer(crs="EPSG:4326", name="Streams 4326"))
        a, _ = self.crossings()
        m = self.build([stream_row(geo, label_field="Name")])
        self.assertEqual([p.label for p in m.other_points], [p.label for p in a])
        for p, q in zip(m.other_points, a):
            self.assertAlmostEqual(p.station, q.station, delta=0.05, msg=p.label)
        self.assertEqual(m.other_points[3].flags, ["runs along the section line for 300 ft"])

    def test_one_stream_split_at_the_line_is_one_crossing(self):
        """(fix 0.3.6) A stream digitised as two features that meet ON the section line (flowlines split at a
        culvert) is one crossing, the first feature's; another stream meeting it there, or the same name elsewhere,
        keeps its own."""
        lyr = self.add(_line_layer("Creeks", [("Split Cr.", "Creek", None, [[(1000.0, 120.0), (1000.0, 0.0)]]),
                                              ("Split Cr.", "Creek", None, [[(1000.0, 0.0), (1010.0, -120.0)]]),
                                              ("Mill Cr.", "Creek", None, [[(1000.0, 0.0), (990.0, -120.0)]]),
                                              ("Split Cr.", "Creek", None, [[(1600.0, 50.0), (1600.0, -50.0)]])]))
        m = self.build([stream_row(lyr, label_field="Name")])
        got = sorted((p.label, round(p.station / FTUS, 3)) for p in m.other_points)
        self.assertEqual(got, [("Mill Cr.", 1000.0), ("Split Cr.", 1000.0), ("Split Cr.", 1600.0)])
        fids = sorted(f.id() for f in lyr.getFeatures())
        split = next(p for p in m.other_points if p.label == "Split Cr." and p.station / FTUS < 1500.0)
        self.assertEqual(split.fid, fids[0])
        self.assertEqual(m.other_layers[0].plotted, 3)

    def test_a_short_stretch_along_the_line_is_a_plain_crossing(self):
        """(fix 0.3.6) Dense vertices a rounding error either side of the section line make a stretch "along" it of
        no length: one plain crossing, not flagged "runs along the section line for 0 ft"."""
        lyr = self.add(_line_layer("Dense", [("Dense", "Creek", None, [[(3500.0, 1.0), (3500.0, 0.0008),
                                                                         (3500.0, -0.0008), (3500.0, -1.0)]])]))
        m = self.build([stream_row(lyr, label_field="Name")])
        self.assertEqual([(p.label, round(p.station / FTUS, 2), p.flags) for p in m.other_points],
                         [("Dense", 3500.0, [])])
        self.assertFalse([w for w in m.warnings if "runs along" in w])
        self.assertEqual(O.ALONG_MIN_FT, 1.0)

    def test_find_crossings_directly(self):
        s = self.settings([])
        crs = self.dem.crs()
        line = resolve_line(s, self.prj, crs)
        sampler = raster_sampler(self.dem, 1, crs, 1.0)
        row = stream_row(self.streams, label_field="Name", elev="field", elev_field="Bed_ft", elev_empty="off")
        pts, no_elev = O.find_crossings(line, self.streams, row, s, crs, sampler, FTUS, self.prj, None)  # no ground
        self.assertEqual(([p.label for p in pts], sorted(no_elev)), (["Clover Cr.", "Clover Cr."], ["Canal", "Ditch 4"]))
        with self.assertRaises(SectionError):
            O.find_crossings(line, self.seeps, row, s, crs, sampler, FTUS, self.prj, None)    # not a line layer
        self.assertEqual(O.ALONG_FLAG.format(n="1,250"), "runs along the section line for 1,250 ft")


class Pieces(_Project):
    def pieces(self, layer=None, **kw):
        s = self.settings([])
        crs = self.dem.crs()
        line = resolve_line(s, self.prj, crs)
        row = area_row(layer or self.areas, **dict(dict(label_field="Name"), **kw))
        return O.find_area_pieces(line, layer or self.areas, row, crs, FTUS, self.prj)

    def test_every_area(self):
        L = line_length()
        expected = [("Edge lot", 0.0, 200.0, False, False), ("Parcel A", 0.0, 300.0, True, False),
                    ("Ring pond", 600.0, 650.0, False, False), ("Ring pond", 750.0, 800.0, False, False),
                    ("Project site", 1000.0, 2000.0, False, False), ("Wetland A", 1200.0, 1500.0, False, False),
                    ("Buffer U", 3000.0, 3100.0, False, False), ("Buffer U", 3300.0, 3400.0, False, False),
                    ("Parcel Z", 4400.0, L, False, True)]                    # Touch: a point only, no piece
        got = self.pieces()
        self.assertEqual([(p.label, p.open_start, p.open_end) for p in got], [(n, a, b) for n, _, _, a, b in expected])
        for p, (name, a, b, _, _) in zip(got, expected):
            self.assertIsInstance(p, AreaPiece)
            self.assertAlmostEqual(p.start, a * FTUS, delta=0.01, msg=name)
            self.assertAlmostEqual(p.end, b * FTUS, delta=0.01, msg=name)
            self.assertTrue(0.0 <= p.start < p.end <= L * FTUS + 1e-9, name)
        line = resolve_line(self.settings([]), self.prj, self.dem.crs())
        self.assertEqual(got[-1].end, vertex_stations(line, FTUS)[-1])          # A′: exactly the line's length
        self.assertEqual(got[0].start, 0.0)
        self.assertEqual([p.start for p in got], sorted(p.start for p in got))
        self.assertEqual({p.type_value for p in got}, {"", })                   # no type field

    def test_a_on_a_polygon_edge_in_another_crs(self):
        """(fix 0.3.6) A layer in another CRS: A (or A′) on a polygon's edge lies a rounding error in or out of it
        after reprojection, and stays a closed end ("Edge lot"); a polygon A lies well inside stays open."""
        want = [(p.label, p.open_start, p.open_end, p.start, p.end) for p in self.pieces()]
        self.assertIn(("Edge lot", False, False), [w[:3] for w in want])
        self.assertIn(("Parcel A", True, False), [w[:3] for w in want])
        for crs in ("EPSG:4326", "EPSG:32610"):
            got = self.pieces(self.add(make_areas_layer(crs=crs, name=f"Areas {crs}")))
            self.assertEqual([(p.label, p.open_start, p.open_end) for p in got], [w[:3] for w in want], crs)
            for p, w in zip(got, want):
                self.assertAlmostEqual(p.start, w[3], delta=0.05, msg=(crs, p.label))
                self.assertAlmostEqual(p.end, w[4], delta=0.05, msg=(crs, p.label))

    def test_types_blank_labels_and_a_bow_tie(self):
        got = self.pieces(type_field="Type", types=["Parcel"])
        self.assertEqual([(p.label, p.type_value) for p in got],
                         [("Edge lot", "Parcel"), ("Parcel A", "Parcel"), ("Parcel Z", "Parcel")])
        self.assertEqual(self.pieces(type_field="Type", types=[NO_TYPES]), [])
        lyr = self.add(_polygon_layer("Odd", [("  ", "x", [[(500.0, 50.0), (550.0, 50.0), (550.0, -50.0),
                                                            (500.0, -50.0)]]),
                                              ("Bow", "x", [[(1000.0, 100.0), (1200.0, -100.0), (1200.0, 100.0),
                                                             (1000.0, -100.0)]]),                 # self-crossing
                                              ("Sliver", "x", [[(2000.0, 0.0), (2000.002, 0.0), (2000.002, 0.001),
                                                                (2000.0, 0.001)]])]))     # 0.002 ft on the line
        got = self.pieces(lyr)
        self.assertEqual([(p.label, round(p.start / FTUS, 3), round(p.end / FTUS, 3)) for p in got],
                         [("", 500.0, 550.0), ("Bow", 1000.0, 1200.0)])      # merged; the sliver dropped
        got = self.pieces(lyr, label_field="")
        self.assertEqual([p.label for p in got], ["", ""])
        with self.assertRaises(SectionError) as cm:
            self.pieces(label_field="Nope")
        self.assertEqual(str(cm.exception), "The label field “Nope” is not in Areas. Choose another field.")
        self.assertEqual(O.MIN_PIECE_FT, 0.01)


class Build(_Project):
    def test_one_row_of_each_kind(self):
        rows = [seep_row(self.seeps, label_field="Name"), stream_row(self.streams, label_field="Name"),
                area_row(self.areas, label_field="Name", name="Areas", bracket="above")]
        m = self.build(rows, [point_row(self.pts, label_field="ExploName")])
        self.assertEqual([o.kind for o in m.other_layers], ["point", "line", "polygon"])
        self.assertEqual([o.plotted for o in m.other_layers], [4, 4, 9])
        self.assertEqual([o.on for o in m.other_layers], [True] * 3)
        self.assertEqual((m.other_layers[2].bracket, m.other_layers[2].bracket_style, m.other_layers[2].edges),
                         ("above", "solid", "off"))
        self.assertEqual(len(m.other_points), 8)
        keys = [(p.station, p.layer_index, p.label) for p in m.other_points]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual({p.kind for p in m.other_points if p.layer_index == 1}, {"crossing"})
        self.assertEqual({p.kind for p in m.other_points if p.layer_index == 0}, {"point"})
        self.assertEqual(len(m.other_areas), 9)
        self.assertEqual({(a.layer_index, a.layer_id, a.layer_name) for a in m.other_areas},
                         {(2, self.areas.id(), "Areas")})
        keys = [(a.start, a.layer_index, a.label) for a in m.other_areas]
        self.assertEqual(keys, sorted(keys))
        self.assertTrue(m.has_points)
        self.assertNotIn(NO_POINTS, m.warnings)
        self.assertTrue(all(isinstance(h, Hit) for h in m.hits))              # no crossing among the hits
        self.assertEqual(len(m.hits), 7)
        # only a polygon row: still points on the section (no NO_POINTS note)
        m = self.build([area_row(self.areas, label_field="Name")])
        self.assertTrue(m.has_points)
        self.assertNotIn(NO_POINTS, m.warnings)
        self.assertEqual(m.other_points, [])

    def test_the_layer_decides_the_kind(self):
        m = self.build([seep_row(self.streams, label_field="Name")])          # stored as a point row
        self.assertEqual(m.other_layers[0].kind, "line")
        self.assertEqual([p.kind for p in m.other_points], ["crossing"] * 4)
        m = self.build([stream_row(self.areas, label_field="Name")])          # a line row on a polygon layer
        self.assertEqual((m.other_layers[0].kind, len(m.other_areas), m.other_points), ("polygon", 9, []))
        m = self.build([area_row(self.areas, visible=False)])                 # off: the layer's kind all the same
        self.assertEqual((m.other_layers[0].kind, m.other_layers[0].on, m.other_areas), ("polygon", False, []))

    def test_a_missing_polygon_layer(self):
        m = self.build([area_row(layer_id="gone", name="Sites"), stream_row(layer_id="gone2")])
        self.assertEqual([(o.kind, o.on) for o in m.other_layers], [("polygon", False), ("line", False)])
        self.assertEqual([w for w in m.warnings if w.startswith("Other points")],
                         ["Other points “Sites”: its layer is no longer in the project; left out.",
                          "Other points “row 2”: its layer is no longer in the project; left out."])
        self.assertIn(NO_POINTS, m.warnings)
        with self.assertRaises(SectionError) as cm:
            self.build([area_row(self.areas, label_field="Nope", name="Sites")])
        self.assertEqual(str(cm.exception), "Sites: The label field “Nope” is not in Areas. Choose another field.")

    def test_hover(self):
        m = self.build([stream_row(self.streams, label_field="Name", name="Streams"),
                        area_row(self.areas, label_field="Name")], [point_row(self.pts, label_field="ExploName")])
        targets = Hv.hover_targets(m)
        self.assertEqual(targets, list(m.hits) + list(m.other_points))
        self.assertFalse(any(isinstance(t, AreaPiece) for t in targets))
        s = self.settings([])
        p = m.other_points[0]
        self.assertEqual(Hv.other_cells(p, s, m)[:2], [("Streams", "Clover Cr.", ""), ("From A", "900 ft", "crossing")])
        self.assertEqual(Hv.strip_cells(p, s, m)[:2], [("Streams", "Clover Cr.", "", ""),
                                                        ("From A", "900 ft", "crossing", "")])
        self.assertEqual(Hv.other_cells(p, s, m)[2], ("Elevation", Hv.elev_text(p.z), "ground line"))
        m = self.build([stream_row(self.streams, label_field="Name", type_field="Type")])
        self.assertEqual(Hv.target_cells(m.other_points[0], s, m)[0], ("Perennial", "Clover Cr.", "Streams"))
        s2 = self.settings([], distance_labels="station")
        self.assertEqual(Hv.other_cells(m.other_points[0], s2, m)[1], ("From A", "9+00", "crossing"))


@timing_test
class Budget(_Project):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import random
        rnd = random.Random(7)
        L = line_length()
        lines = []
        for i in range(2000):                     # 20 crossing the line, the rest 400 to 3,000 ft off it
            if i < 20:
                st = 100.0 + i * 200.0
                lines.append((f"C-{i}", "Creek", None, [[(st, 80.0), (st + 30.0, -80.0)]]))
            else:
                st, off = rnd.uniform(0.0, L), rnd.choice((-1, 1)) * rnd.uniform(400.0, 3000.0)
                lines.append((f"F-{i}", "Creek", None, [[(st, off), (st + 60.0, off + 40.0), (st + 120.0, off)]]))
        polys = []
        for i in range(5000):
            if i < 20:
                st = 50.0 + i * 220.0
                polys.append((f"P-{i}", "Parcel", [[(st, 60.0), (st + 100.0, 60.0), (st + 100.0, -60.0),
                                                    (st, -60.0)]]))
            else:
                st, off = rnd.uniform(0.0, L), rnd.choice((-1, 1)) * rnd.uniform(400.0, 3000.0)
                polys.append((f"Q-{i}", "Parcel", [[(st, off), (st + 80.0, off), (st + 80.0, off + 80.0),
                                                    (st, off + 80.0)]]))
        cls.many_lines = _line_layer("Many lines", lines)
        cls.many_polys = _polygon_layer("Many parcels", polys)
        cls.prj.addMapLayers([cls.many_lines, cls.many_polys])

    def test_a_large_line_and_polygon_layer(self):
        s = self.settings([stream_row(self.many_lines, label_field="Name"),
                           area_row(self.many_polys, label_field="Name")])
        build_section(s, self.prj)                                             # warm (the DEM, the caches)
        t = time.perf_counter()
        m = build_section(s, self.prj)
        dt = time.perf_counter() - t
        self.assertEqual([o.plotted for o in m.other_layers], [20, 20])
        self.assertLessEqual(dt, budget(1.5), f"build with 2,000 lines and 5,000 polygons took {dt:.3f} s")
        print(f"\n  build with 2,000 lines and 5,000 polygons: {dt:.3f} s")


if __name__ == "__main__":
    unittest.main()
