"""Other points (0.3.3, DESIGN.md decision 22), the core part: core/others.py find_other_points and the Other points
rows in build_section. Seeps and springs are chosen by the explorations' own rule (the shared "within" distance, flat
end caps) and placed on the ground line, at the LIDAR or at an elevation field, with the fallbacks of each."""
import math
import unittest

from tests.fixtures import (CRS, SEEPS, TOLERANCE, load_project, make_seeps_layer, plane_z, point_at, point_row,
                            seep_row, start_app, write_gpkg)
from tests.test_units import FTUS

APP = start_app()

from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsVectorLayer  # noqa: E402
from qgis.PyQt.QtCore import QMetaType  # noqa: E402

from xsections.core import others as O  # noqa: E402
from xsections.core.build import build_section  # noqa: E402
from xsections.core.model import (NO_POINTS, NO_TYPES, OtherLayerInfo, OtherPoint, SectionError,  # noqa: E402
                                  Settings)
from xsections.core.section import ground_profile, raster_sampler, resolve_line  # noqa: E402

ON_SECTION = ["S-1", "S-2", "S-5", "S-3"]          # by station; S-4 is 1 ft beyond the tolerance


def seeps(layer, **kw):
    return seep_row(layer, label_field="Name", **kw)


def lidar(x, y):
    return plane_z(x, y)


class OtherPointsCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        cls.seeps = make_seeps_layer()
        cls.prj.addMapLayer(cls.seeps)

    def settings(self, others, rows=(), **kw):
        s = Settings(line_layer_id=self.lines.id(), line_fid=next(self.lines.getFeatures()).id(),
                     dem_layer_id=self.dem.id(), tolerance_ft=TOLERANCE, point_layers=list(rows),
                     other_points=list(others))
        for k, v in kw.items():
            setattr(s, k, v)
        return s

    def build(self, others, rows=(), **kw):
        s = self.settings(others, rows, **kw)
        return build_section(s, self.prj), s

    def points(self, **kw):
        m, _ = self.build([seeps(self.seeps, **kw)])
        return {p.label: p for p in m.other_points}, m

    def layer(self, rows, name="extra points"):
        """A memory point layer of (Name, Type, Elev_ft, station, offset_left) rows."""
        lyr = QgsVectorLayer(f"Point?crs={CRS}", name, "memory")
        lyr.dataProvider().addAttributes([QgsField("Name", QMetaType.Type.QString),
                                          QgsField("Type", QMetaType.Type.QString),
                                          QgsField("Elev_ft", QMetaType.Type.Double)])
        lyr.updateFields()
        feats = []
        for name, typ, elev, st, off in rows:
            f = QgsFeature(lyr.fields())
            f.setAttributes([name, typ, elev])
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*point_at(st, off))))
            feats.append(f)
        lyr.dataProvider().addFeatures(feats)
        self.prj.addMapLayer(lyr)
        self.addCleanup(self.prj.removeMapLayer, lyr.id())
        return lyr

    # ---- selection: the explorations' rule
    def test_within_the_tolerance_and_end_caps(self):
        by, m = self.points()
        self.assertEqual([p.label for p in m.other_points], ON_SECTION)
        info = m.other_layers[0]
        self.assertIsInstance(info, OtherLayerInfo)
        self.assertEqual((info.on, info.plotted, info.near, info.beyond, info.no_elevation), (True, 4, 1, [], []))
        for name, typ, st, off, _ in [r for r in SEEPS if r[0] in ON_SECTION]:
            p = by[name]
            self.assertIsInstance(p, OtherPoint)
            self.assertAlmostEqual(p.station, st * FTUS, delta=0.01, msg=name)
            self.assertAlmostEqual(p.offset, abs(off) * FTUS, delta=0.01, msg=name)
            self.assertEqual(p.side, "L" if off > 0 else "R", name)
            self.assertEqual(p.type_value, "", name)                       # no type field: every point, no type
            x, y = point_at(st, off)
            self.assertAlmostEqual(p.x, x, delta=1e-6)
            self.assertAlmostEqual(p.y, y, delta=1e-6)
        # 0.3.5: the direction of projection onto the line: S-1 lies north of it (projected S), S-2 south
        self.assertEqual(by["S-1"].direction, "S")
        self.assertEqual(by["S-2"].direction, "N")

    def test_the_same_selection_as_explorations(self):
        """The explorations layer as Other points: exactly the explorations' stations, offsets and end caps."""
        hits = build_section(self.settings([], [point_row(self.pts, label_field="ExploName")]), self.prj).hits
        m, _ = self.build([seep_row(self.pts, label_field="ExploName")])
        self.assertEqual([p.label for p in m.other_points], [h.label for h in hits])
        for p, h in zip(m.other_points, hits):
            self.assertEqual((p.fid, p.station, p.offset, p.side, p.direction, p.x, p.y),
                             (h.fid, h.station, h.offset, h.side, h.direction, h.x, h.y), p.label)
            self.assertEqual((p.ground_at_station, p.in_gap), (h.ground_at_station, h.in_gap))
            self.assertTrue(p.ground_at_point == h.ground_at_point or
                            (math.isnan(p.ground_at_point) and math.isnan(h.ground_at_point)))
        self.assertEqual(m.other_layers[0].beyond, ["B-pre", "B-post"])
        self.assertEqual(m.beyond_ends, [])                                  # the warning lists explorations only
        m, _ = self.build([seep_row(self.pts, label_field="ExploName")], tolerance_ft=100.0)
        self.assertEqual(m.other_layers[0].near, 1)                          # B-2 at 120 ft
        self.assertNotIn("B-2", [p.label for p in m.other_points])

    def test_types(self):
        by, _ = self.points(type_field="Type", types=["Spring"])
        self.assertEqual(list(by), ["S-3"])
        self.assertEqual(by["S-3"].type_value, "Spring")
        by, _ = self.points(type_field="Type")
        self.assertEqual(list(by), ON_SECTION)                               # no types ticked: all
        by, m = self.points(type_field="Type", types=[NO_TYPES])
        self.assertEqual(by, {})
        self.assertEqual(m.other_layers[0].near, 0)
        by, _ = self.points(type_field="Type", types=[""])
        self.assertEqual(by, {})
        lyr = self.layer([("N-1", None, None, 500.0, 5.0), ("N-2", "", None, 700.0, 5.0),
                          ("N-3", "Seep", None, 900.0, 5.0)])
        m, _ = self.build([seep_row(lyr, label_field="Name", type_field="Type", types=[""])])
        self.assertEqual([p.label for p in m.other_points], ["N-1", "N-2"])
        self.assertEqual([p.type_value for p in m.other_points], ["", ""])

    # ---- placement
    def test_on_the_ground_line(self):
        by, m = self.points()
        for p in m.other_points:
            self.assertEqual((p.how, p.fell_back, p.field_value, p.in_gap, p.flags), ("line", False, None, False, []))
            self.assertEqual(p.z, p.ground_at_station)
            self.assertEqual(p.ground_at_station, m.ground.z_at(p.station))
            self.assertAlmostEqual(p.ground_at_point, lidar(p.x, p.y), delta=0.01)

    def test_at_the_lidar(self):
        by, m = self.points(elev="lidar")
        for p in m.other_points:
            self.assertEqual((p.how, p.fell_back, p.field_value, p.flags), ("lidar", False, None, []))
            self.assertEqual(p.z, p.ground_at_point)
            self.assertAlmostEqual(p.z, lidar(p.x, p.y), delta=0.01)
        self.assertNotAlmostEqual(by["S-2"].z, by["S-2"].ground_at_station, delta=0.05)   # 30 ft off the line

    def test_from_a_field_and_its_fallbacks(self):
        by, m = self.points(elev="field", elev_field="Elev_ft")              # where it is empty: the ground line
        s1, s2, s3, s5 = by["S-1"], by["S-2"], by["S-3"], by["S-5"]
        self.assertAlmostEqual(s2.z, round(lidar(s2.x, s2.y) + 1.4, 2), delta=1e-9)
        self.assertEqual((s2.how, s2.field_value, s2.fell_back, s2.flags), ("field", s2.z, False, []))
        self.assertEqual((s5.how, s5.fell_back), ("field", False))
        for p in (s1, s3):                                                   # NULL, and 0 (missing)
            self.assertEqual((p.how, p.field_value, p.fell_back), ("line", None, True), p.label)
            self.assertEqual(p.z, p.ground_at_station)
        self.assertEqual(m.other_layers[0].no_elevation, [])
        by, m = self.points(elev="field", elev_field="Elev_ft", elev_empty="lidar")
        for p in (by["S-1"], by["S-3"]):
            self.assertEqual((p.how, p.fell_back, p.z), ("lidar", True, p.ground_at_point), p.label)
        self.assertEqual(by["S-2"].how, "field")
        by, m = self.points(elev="field", elev_field="Elev_ft", elev_empty="off")
        self.assertEqual(list(by), ["S-2", "S-5"])
        self.assertEqual(sorted(m.other_layers[0].no_elevation), ["S-1", "S-3"])
        self.assertEqual(m.other_layers[0].plotted, 2)
        # 0 is a value when zeros are not missing (the shared rule): kept, and far from LIDAR
        m2, _ = self.build([seeps(self.seeps, elev="field", elev_field="Elev_ft")], zero_is_missing=False)
        s3 = next(p for p in m2.other_points if p.label == "S-3")
        self.assertEqual((s3.how, s3.z, s3.field_value), ("field", 0.0, 0.0))
        self.assertTrue(s3.flags and s3.flags[0].startswith("Elev_ft 0 ft is "), s3.flags)
        self.assertTrue(s3.flags[0].endswith(" ft from LIDAR"))
        # a field elevation named for another mode is not read
        by, _ = self.points(elev="line", elev_field="Elev_ft")
        self.assertTrue(all(p.field_value is None and p.how == "line" for p in by.values()))

    def test_a_field_value_far_from_lidar_is_flagged_and_kept(self):
        x, y = point_at(1200.0, 25.0)
        lyr = self.layer([("F-1", "Seep", round(lidar(x, y) + 30.0, 2), 1200.0, 25.0),
                          ("F-2", "Seep", round(lidar(x, y) - 20.0, 2), 1250.0, 25.0)])
        row = seep_row(lyr, label_field="Name", elev="field", elev_field="Elev_ft")
        m, _ = self.build([row])
        f1, f2 = m.other_points
        self.assertEqual((f1.how, f1.fell_back), ("field", False))
        self.assertEqual(f1.flags, [f"Elev_ft {f1.z:.2f}".rstrip("0").rstrip(".") + " ft is 30.0 ft from LIDAR"])
        self.assertEqual(f2.flags, [])                                       # 20 ft: within the 25 ft check
        self.assertIn(f"F-1: {f1.flags[0]}", m.warnings)
        m, _ = self.build([row], top_max_diff_ft=0.0)                        # no check
        self.assertEqual(m.other_points[0].flags, [])
        m, _ = self.build([row], top_max_diff_ft=10.0)                       # the shared distance
        self.assertEqual([bool(p.flags) for p in m.other_points], [True, True])

    def test_no_lidar_and_a_dem_gap(self):
        lyr = self.layer([("H-1", "Seep", 999.0, 3990.0, 10.0)])            # in the DEM's nodata disc
        m, _ = self.build([seep_row(lyr, label_field="Name")])
        p = m.other_points[0]
        self.assertTrue(p.in_gap)
        self.assertTrue(math.isnan(p.ground_at_point))
        self.assertEqual(p.ground_at_station, m.ground.nearest_valid(p.station))
        self.assertEqual((p.z, p.how, p.flags), (p.ground_at_station, "line", [O.GAP_FLAG]))
        self.assertIn("H-1: station in a DEM gap", m.warnings)
        m, _ = self.build([seep_row(lyr, label_field="Name", elev="lidar")])
        p = m.other_points[0]
        self.assertEqual((p.how, p.fell_back, p.z), ("line", True, p.ground_at_station))
        self.assertEqual(p.flags, [O.GAP_FLAG, "no LIDAR at the point: on the ground line"])
        self.assertIn("H-1: no LIDAR at the point: on the ground line", m.warnings)
        m, _ = self.build([seep_row(lyr, label_field="Name", elev="field", elev_field="Elev_ft")])
        self.assertEqual((m.other_points[0].how, m.other_points[0].z), ("field", 999.0))
        self.assertEqual(m.other_points[0].flags, [O.GAP_FLAG])               # no LIDAR: nothing to check against

    # ---- rows, sorting, the model
    def test_rows_sorted_and_stamped(self):
        lyr = self.layer([("A-1", "Spring", None, 1650.0, 10.0), ("A-0", "Spring", None, 1650.0, 10.0)],
                         name="Springs")                                    # one spot: by label
        rows = [seeps(self.seeps, shape="circle", color="#FF0000", size=40, elev="lidar"),
                seep_row(lyr, label_field="Name", name="My springs"),
                seeps(self.seeps, name="Seeps again")]                      # the same spots: by row
        m, _ = self.build(rows)
        keys = [(p.station, p.layer_index, p.label) for p in m.other_points]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual([(p.label, p.layer_index) for p in m.other_points],
                         [("S-1", 0), ("S-1", 2), ("S-2", 0), ("S-2", 2), ("A-0", 1), ("A-1", 1), ("S-5", 0),
                          ("S-5", 2), ("S-3", 0), ("S-3", 2)])
        self.assertEqual({(p.layer_index, p.layer_id, p.layer_name) for p in m.other_points},
                         {(0, self.seeps.id(), "Seeps"), (1, lyr.id(), "My springs"),
                          (2, self.seeps.id(), "Seeps again")})
        a, b, _ = m.other_layers
        self.assertEqual((a.index, a.layer_id, a.name, a.layer_name, a.shape, a.color, a.size, a.elev, a.on),
                         (0, self.seeps.id(), "Seeps", "Seeps", "circle", "#ff0000", 20.0, "lidar", True))
        self.assertEqual((b.name, b.layer_name, b.shape, b.color, b.size, b.elev, b.elev_empty, b.plotted),
                         ("My springs", "Springs", "asterisk", "#1f6fb2", 7.0, "line", "line", 2))
        self.assertEqual(a.row, rows[0])

    def test_has_points(self):
        m, _ = self.build([seeps(self.seeps)])
        self.assertFalse(m.has_explorations)
        self.assertTrue(m.has_points)
        self.assertNotIn(NO_POINTS, m.warnings)
        self.assertEqual(m.hits, [])
        self.assertFalse(any(w.startswith("No explorations within") for w in m.warnings))
        m, _ = self.build([seeps(self.seeps, visible=False)])
        self.assertFalse(m.has_points)
        self.assertIn(NO_POINTS, m.warnings)
        self.assertEqual(m.other_layers[0].on, False)
        m, _ = self.build([])
        self.assertFalse(m.has_points)
        m, _ = self.build([seeps(self.seeps)], [point_row(self.pts, label_field="ExploName")])
        self.assertTrue(m.has_explorations and m.has_points)
        self.assertEqual(len(m.hits), 7)
        self.assertEqual(len(m.other_points), 4)
        m, _ = self.build([seep_row(layer_id="")])                           # no layer chosen: skipped quietly
        self.assertEqual((m.other_layers[0].on, m.other_layers[0].name), (False, "row 1"))
        self.assertFalse(any(w.startswith("Other points") for w in m.warnings))

    def test_a_missing_layer_is_left_out_with_a_warning(self):
        rows = [seep_row(layer_id="gone", name="Springs"), seep_row(layer_id="gone2"), seeps(self.seeps),
                seep_row(self.lines, label_field="name"), seep_row(layer_id="gone3", visible=False)]
        m, _ = self.build(rows, [point_row(self.pts, label_field="ExploName")])
        self.assertEqual(len(m.hits), 7)                                     # the explorations are still built
        self.assertEqual([p.label for p in m.other_points], ON_SECTION)
        gone = [w for w in m.warnings if w.startswith("Other points")]
        self.assertEqual(gone, ["Other points “Springs”: its layer is no longer in the project; left out.",
                                "Other points “row 2”: its layer is no longer in the project; left out.",
                                "Other points “Section_Lines”: its layer is no longer in the project; left out."])
        self.assertEqual([o.on for o in m.other_layers], [False, False, True, False, False])
        self.assertEqual([o.name for o in m.other_layers], ["Springs", "row 2", "Seeps", "Section_Lines", "row 5"])
        # the order of the warnings: after the DEM notes, before the explorations' notes
        i = m.warnings.index(gone[0])
        self.assertLess(m.warnings.index(next(w for w in m.warnings if w.startswith("No DEM data along"))), i)
        self.assertLess(i, m.warnings.index(next(w for w in m.warnings if w.startswith("Left out past the ends"))))
        # only gone rows: the ground line, and the note
        m, _ = self.build([seep_row(layer_id="gone", name="Springs")])
        self.assertFalse(m.has_points)
        self.assertIn(NO_POINTS, m.warnings)

    def test_a_missing_field_is_an_error_naming_the_row(self):
        with self.assertRaises(SectionError) as cm:
            self.build([seeps(self.seeps, elev="field", elev_field="Nope")])
        self.assertEqual(str(cm.exception), "Seeps: The elevation field “Nope” is not in Seeps. Choose another field.")
        with self.assertRaises(SectionError) as cm:
            self.build([seep_row(self.seeps, label_field="Nope", name="My seeps")])
        self.assertTrue(str(cm.exception).startswith("My seeps: The label field “Nope”"), str(cm.exception))
        m, _ = self.build([seeps(self.seeps, elev="lidar", elev_field="Nope")])  # not read: no error
        self.assertEqual(len(m.other_points), 4)

    def test_find_other_points_directly(self):
        s = self.settings([])
        crs = self.dem.crs()
        line = resolve_line(s, self.prj, crs)
        sampler = raster_sampler(self.dem, 1, crs, 1.0)
        ground = ground_profile(line, sampler, 3.0 * FTUS, FTUS)
        row = seeps(self.seeps, elev="field", elev_field="Elev_ft", elev_empty="off")
        pts, beyond, near, no_elev = O.find_other_points(line, self.seeps, row, s, crs, sampler, FTUS, self.prj,
                                                         ground)
        self.assertEqual([p.label for p in pts], ["S-2", "S-5"])
        self.assertEqual((beyond, near, sorted(no_elev)), ([], 1, ["S-1", "S-3"]))
        pts2, *_ = O.find_other_points(line, self.seeps, row, s, crs, sampler, FTUS, self.prj, None)   # no ground
        self.assertEqual([p.label for p in pts2], ["S-2", "S-5"])
        with self.assertRaises(SectionError):
            O.find_other_points(line, self.lines, row, s, crs, sampler, FTUS, self.prj, ground)
        with self.assertRaises(SectionError):
            O.find_other_points(line, self.seeps, row, Settings(tolerance_ft=0.0), crs, sampler, FTUS, self.prj,
                                ground)

    def test_a_geopackage_layer(self):
        gpkg = write_gpkg(make_seeps_layer(), "seeps_gpkg")
        self.prj.addMapLayer(gpkg)
        self.addCleanup(self.prj.removeMapLayer, gpkg.id())
        m, _ = self.build([seep_row(gpkg, label_field="Name", elev="field", elev_field="Elev_ft")])
        self.assertEqual([p.label for p in m.other_points], ON_SECTION)
        self.assertEqual([p.how for p in m.other_points], ["line", "field", "field", "line"])


if __name__ == "__main__":
    unittest.main()
