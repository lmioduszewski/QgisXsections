"""Each exploration's colour from its point layer's own QGIS style (0.3.4, DESIGN.md decision 23, build spec 3.2-3.3):
core.symbology on memory layers with fixed renderers (a memory layer's default symbol has a random colour), and the
build of rows drawn in Color (plotted and left-off hits stamped, Black and Gray rows never read the style, a style that
can't be read draws the row in black, the 3-row budget)."""
import time
import unittest
from unittest import mock

from tests.fixtures import (CUMBERLAND_AESI, TYPE_CATS, budget, categorized_renderer, load_project, make_dense_layer,
                            make_others_layer, make_supply_layer, point_row, rule_renderer, single_renderer,
                            start_app, timing_test)

APP = start_app()

from qgis.core import (QgsApplication, QgsDataDefinedSizeLegend, QgsExpressionContext,  # noqa: E402
                       QgsExpressionContextUtils, QgsFeature, QgsField, QgsGeometry, QgsGraduatedSymbolRenderer,
                       QgsHeatmapRenderer, QgsMarkerSymbol, QgsMergedFeatureRenderer, QgsNullSymbolRenderer,
                       QgsPointClusterRenderer, QgsPointDisplacementRenderer, QgsPointXY, QgsProperty,
                       QgsRendererRange, QgsRuleBasedRenderer, QgsSimpleMarkerSymbolLayer, QgsSingleSymbolRenderer,
                       QgsSymbolLayer, QgsVectorLayer)
from qgis.PyQt.QtCore import QMetaType  # noqa: E402
from qgis.PyQt.QtGui import QColor  # noqa: E402

from tests.test_point_layers import explo_row, others_row, rows_settings, supply_row  # noqa: E402
from xsections.core import symbology as Y  # noqa: E402
from xsections.core.build import build_section  # noqa: E402
from xsections.core.model import (LOOK_GRAY, NO_TYPES, STYLE_KINDS, Hit, LayerStyle, PointLayerInfo,  # noqa: E402
                                  StyleItem, hidden_key, line_key)

# (Name, T, D, Col): a type for categories and rules, a depth for ranges, a colour field for data-defined fills
FEATURES = [("B-1", "Boring", 5.0, "#ff0000"), ("CPT-1", "CPT", 15.0, "#00ff00"), ("N-1", None, 25.0, None),
            ("Z-1", "ZZ", 35.0, "#0000ff"), ("E-1", "", 45.0, "#fafafa")]
NAMES = [f[0] for f in FEATURES]


def make_layer(name="pts"):
    """A memory point layer of FEATURES (EPSG:2927); its renderer is set by each test."""
    T = QMetaType.Type
    lyr = QgsVectorLayer("Point?crs=EPSG:2927", name, "memory")
    lyr.dataProvider().addAttributes([QgsField("Name", T.QString), QgsField("T", T.QString), QgsField("D", T.Double),
                                      QgsField("Col", T.QString)])
    lyr.updateFields()
    feats = []
    for i, attrs in enumerate(FEATURES):
        f = QgsFeature(lyr.fields())
        f.setAttributes(list(attrs))
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(1_200_000.0 + 10.0 * i, 650_000.0)))
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    lyr.updateExtents()
    return lyr


def marker(color="#808080", outline="#232323", **props):
    return QgsMarkerSymbol.createSimple(dict({"color": color, "outline_color": outline}, **props))


def ranges(*spec):
    """A graduated renderer's ranges: spec (lower, upper, colour, label)."""
    return [QgsRendererRange(lo, hi, marker(c), label) for lo, hi, c, label in spec]


class Model(unittest.TestCase):
    def test_dataclasses(self):
        self.assertEqual(STYLE_KINDS, ("single", "categorized", "graduated", "rule", "other", "none"))
        self.assertEqual(LayerStyle(), LayerStyle(kind="none", field="", name="", items=[]))
        self.assertIsNot(LayerStyle().items, LayerStyle().items)
        self.assertEqual(StyleItem("0", "", "#123456"), StyleItem(key="0", label="", color="#123456", on=True))
        h = Hit(fid=1, label="B-1", type_value="", x=0.0, y=0.0, station=0.0, offset=0.0, side="L", direction="N",
                ground_at_station=0.0, ground_at_point=0.0, top=None, top_source="none", bottom=None)
        self.assertEqual(h.style_rank, -1)
        info = PointLayerInfo(index=0, layer_id="", name="x", layer_name="", look="color", color="", in_range=True,
                              on=True, row={})
        self.assertIsNone(info.style)


class SymbolColor(unittest.TestCase):
    """symbol_color: the fill, else the outline, else the next symbol layer, else black."""

    def test_fill_and_outline(self):
        self.assertEqual(Y.symbol_color(marker("#df9560")), "#df9560")
        self.assertEqual(Y.symbol_color(marker("#DF9560")), "#df9560")                     # "#rrggbb", lower case
        self.assertEqual(Y.symbol_color(marker("#ffffff", "#aa5500")), "#aa5500")          # hollow: its outline
        self.assertEqual(Y.symbol_color(marker("#ffffff", "#fdfdfd")), "#000000")          # all white: black
        self.assertEqual(Y.symbol_color(marker("255,0,0,0", "#0000ff")), "#0000ff")        # transparent fill
        self.assertEqual(Y.symbol_color(None), "#000000")

    def test_unfilled_shapes_take_the_outline(self):
        for shape in ("cross", "cross2", "line", "x"):
            sym = marker("#ff0000", "#0000ff", name=shape)
            self.assertEqual(Y.symbol_color(sym), "#0000ff", shape)
        self.assertEqual(Y.symbol_color(marker("#ff0000", "#0000ff", name="square")), "#ff0000")

    def test_near_white(self):
        self.assertEqual(Y.NEAR_WHITE, 230)
        self.assertEqual(Y.symbol_color(marker("#ffff01", "#123456")), "#ffff01")          # yellow stays yellow
        self.assertEqual(Y.symbol_color(marker("#fafafa", "#123456")), "#123456")
        self.assertEqual(Y.symbol_color(marker("#e6e6e6", "#123456")), "#123456")          # 230: white
        self.assertEqual(Y.symbol_color(marker("#e5e5e5", "#123456")), "#e5e5e5")          # 229: a colour

    def test_opacity_is_not_drawn(self):
        self.assertEqual(Y.symbol_color(marker("223,149,96,128")), "#df9560")
        sym = marker("#df9560")
        sym.setOpacity(0.4)
        self.assertEqual(Y.symbol_color(sym), "#df9560")

    def test_an_outline_that_is_not_drawn(self):
        self.assertEqual(Y.symbol_color(marker("#ffffff", "#0000ff", outline_style="no")), "#000000")
        self.assertEqual(Y.symbol_color(marker("#ff0000", "#0000ff", outline_style="no")), "#ff0000")

    def test_symbol_layers_in_order(self):
        sym = marker("#ffffff", "#ffffff")                                                  # white first ...
        second = QgsSimpleMarkerSymbolLayer()
        second.setColor(QColor("#cc0000"))
        sym.appendSymbolLayer(second)
        self.assertEqual(Y.symbol_color(sym), "#cc0000")                                   # ... the second's
        sym = marker("#00ff00")
        sym.symbolLayer(0).setEnabled(False)                                                # a disabled layer
        third = QgsSimpleMarkerSymbolLayer()
        third.setColor(QColor("#cc0000"))
        sym.appendSymbolLayer(third)
        self.assertEqual(Y.symbol_color(sym), "#cc0000")
        sym.symbolLayer(1).setEnabled(False)
        self.assertEqual(Y.symbol_color(sym), "#000000")                                   # none enabled

    def test_data_defined_colours_per_feature(self):
        lyr = make_layer()
        sym = marker("#808080", "#232323")
        sym.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.Property.FillColor, QgsProperty.fromField("Col"))
        hollow = marker("#ffffff", "#808080")
        hollow.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.Property.StrokeColor, QgsProperty.fromField("Col"))
        want_fill = {"B-1": "#ff0000", "CPT-1": "#00ff00", "N-1": "#808080", "Z-1": "#0000ff", "E-1": "#232323"}
        want_line = {"B-1": "#ff0000", "CPT-1": "#00ff00", "N-1": "#808080", "Z-1": "#0000ff", "E-1": "#000000"}
        for f in lyr.getFeatures():
            ec = QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(lyr))
            ec.setFeature(f)
            self.assertEqual(Y.symbol_color(sym, ec), want_fill[f["Name"]], f["Name"])      # NULL: the static one
            self.assertEqual(Y.symbol_color(hollow, ec), want_line[f["Name"]], f["Name"])
        self.assertEqual(Y.symbol_color(sym), "#808080")                                   # no feature: static
        self.assertEqual(Y.symbol_color(hollow), "#808080")


class LayerStyles(unittest.TestCase):
    """layer_style: the kind, class field and legend items, read without any feature."""

    def setUp(self):
        self.lyr = make_layer()

    def style(self, renderer):
        self.lyr.setRenderer(renderer)
        return Y.layer_style(self.lyr)

    def test_single(self):
        self.assertEqual(self.style(single_renderer("#123456")),
                         LayerStyle(kind="single", field="", name="", items=[StyleItem("0", "", "#123456", True)]))
        st = self.style(single_renderer("#ffffff", outline="#3fcaa2"))                       # a hollow marker
        self.assertEqual([(i.label, i.color) for i in st.items], [("", "#3fcaa2")])

    def test_categorized(self):
        st = self.style(categorized_renderer("ExploType", CUMBERLAND_AESI))
        self.assertEqual((st.kind, st.field, st.name), ("categorized", "ExploType", ""))
        self.assertEqual([(i.label, i.color, i.on) for i in st.items],
                         [(lab or Y.NO_VALUE_LABEL, c, True) for _v, lab, c in CUMBERLAND_AESI])
        self.assertEqual(len(st.items), 13)
        self.assertEqual(st.items[-1].label, "(no value)")
        self.assertEqual([i.key for i in st.items], [i.ruleKey() for i in self.lyr.renderer().legendSymbolItems()])

    def test_a_category_unticked(self):
        self.lyr.setRenderer(categorized_renderer("T", TYPE_CATS))
        key = self.lyr.renderer().legendSymbolItems()[1].ruleKey()
        self.lyr.renderer().checkLegendSymbolItem(key, False)                               # the Layers panel tick
        self.assertEqual([i.on for i in Y.layer_style(self.lyr).items], [True, False, True, True, True])

    def test_blank_category_labels(self):
        st = self.style(categorized_renderer("T", [("Boring", "", "#df9560"), (["CPT", "ZZ"], "", "#cec063"),
                                                   ("", "", "#123456"), (None, "", "#e049db"),
                                                   ("Test Pit", "  ", "#80a7ea")]))
        self.assertEqual([i.label for i in st.items], ["Boring", "CPT, ZZ", "(no value)", "(no value)", "Test Pit"])

    def test_graduated(self):
        st = self.style(QgsGraduatedSymbolRenderer("D", ranges((0, 20, "#fee5d9", ""), (20, 40.5, "#fb6a4a", ""),
                                                               (40.5, 60, "#a50f15", "Deep"))))
        self.assertEqual((st.kind, st.field), ("graduated", "D"))
        self.assertEqual([(i.label, i.color) for i in st.items],
                         [("0 - 20", "#fee5d9"), ("20 - 40.5", "#fb6a4a"), ("Deep", "#a50f15")])

    def test_rule_based(self):
        """Nested rules with a parent without a symbol (not an item), an ELSE without a label, an inactive rule (off),
        a rule named by its filter (cut to 40 characters)."""
        root = QgsRuleBasedRenderer.Rule(None)
        root.appendChild(QgsRuleBasedRenderer.Rule(marker("#aa0000"), 0, 0, "\"T\" = 'Boring'", "Borings"))
        group = QgsRuleBasedRenderer.Rule(None, 0, 0, "\"T\" IN ('CPT', 'ZZ')", "Group")
        group.appendChild(QgsRuleBasedRenderer.Rule(marker("#00aa00"), 0, 0, "\"T\" = 'CPT'", "CPTs"))
        group.appendChild(QgsRuleBasedRenderer.Rule(marker("#0000aa"), 0, 0, "\"T\" = 'ZZ'", ""))
        root.appendChild(group)
        off = QgsRuleBasedRenderer.Rule(marker("#999999"), 0, 0, "\"Name\" = 'N-1'", "Off rule")
        off.setActive(False)
        root.appendChild(off)
        long = "\"Name\" LIKE 'B-%' AND \"D\" > 1 AND \"Col\" IS NOT NULL"
        root.appendChild(QgsRuleBasedRenderer.Rule(marker("#dd8800"), 0, 0, long, ""))
        root.appendChild(QgsRuleBasedRenderer.Rule(marker("#555555"), 0, 0, "ELSE", ""))
        st = self.style(QgsRuleBasedRenderer(root))
        self.assertEqual((st.kind, st.field), ("rule", ""))
        self.assertEqual([(i.label, i.color, i.on) for i in st.items],
                         [("Borings", "#aa0000", True), ("CPTs", "#00aa00", True), ("\"T\" = 'ZZ'", "#0000aa", True),
                          ("Off rule", "#999999", False), (long[:39] + "…", "#dd8800", True),
                          ("(other values)", "#555555", True)])
        self.assertEqual(len(st.items[4].label), 40)
        self.assertEqual(Y.OTHER_VALUES_LABEL, "(other values)")

    def test_wrappers_are_read_through(self):
        for wrapper in (QgsPointDisplacementRenderer(), QgsPointClusterRenderer()):
            wrapper.setEmbeddedRenderer(categorized_renderer("T", TYPE_CATS))
            st = self.style(wrapper)
            self.assertEqual((st.kind, st.field, len(st.items)), ("categorized", "T", 5), wrapper.type())
            self.assertEqual([i.color for i in st.items], [c for _v, _l, c in TYPE_CATS])

    def test_other_renderers(self):
        st = self.style(QgsMergedFeatureRenderer(categorized_renderer("T", TYPE_CATS)))
        name = QgsApplication.rendererRegistry().rendererMetadata("mergedFeatureRenderer").visibleName()
        self.assertTrue(name)
        self.assertEqual((st.kind, st.name, len(st.items)), ("other", name, 5))

    def test_no_symbols(self):
        self.assertEqual(self.style(QgsHeatmapRenderer()), LayerStyle("none"))
        self.assertEqual(self.style(QgsNullSymbolRenderer()), LayerStyle("none"))
        bad = QgsVectorLayer("C:/no/such/folder/points.shp", "gone", "ogr")             # no renderer at all
        self.assertIsNone(bad.renderer())
        self.assertEqual(Y.layer_style(bad), LayerStyle("none"))
        self.assertEqual(Y.layer_style(None), LayerStyle("none"))
        self.assertEqual(Y.read_styles(bad, [1, 2]), (LayerStyle("none"), {1: (-1, ""), 2: (-1, "")}))

    def test_reads_no_feature(self):
        self.lyr.setRenderer(categorized_renderer("T", TYPE_CATS))
        with mock.patch.object(self.lyr, "getFeatures") as gf:
            st = Y.layer_style(self.lyr)
        gf.assert_not_called()
        self.assertEqual(len(st.items), 5)


class ReadStyles(unittest.TestCase):
    """read_styles: the (item index, colour) QGIS draws each requested feature with."""

    def setUp(self):
        self.lyr = make_layer()
        self.fid = {f["Name"]: f.id() for f in self.lyr.getFeatures()}

    def read(self, renderer=None, names=NAMES):
        if renderer is not None:
            self.lyr.setRenderer(renderer)
        st, out = Y.read_styles(self.lyr, [self.fid[n] for n in names])
        by_fid = {v: k for k, v in self.fid.items()}
        return st, {by_fid[fid]: v for fid, v in out.items()}

    def test_categorized(self):
        """A value without a category is drawn with the NULL category (the catch-all), as QGIS draws it; an unticked
        category draws nothing."""
        _st, got = self.read(categorized_renderer("T", TYPE_CATS))
        self.assertEqual(got, {"B-1": (0, "#df9560"), "CPT-1": (3, "#cec063"), "N-1": (4, "#e049db"),
                               "Z-1": (4, "#e049db"), "E-1": (4, "#e049db")})
        r = self.lyr.renderer()
        r.checkLegendSymbolItem(r.legendSymbolItems()[3].ruleKey(), False)
        _st, got = self.read()
        self.assertEqual((got["CPT-1"], got["B-1"]), ((-1, ""), (0, "#df9560")))

    def test_null_and_empty_categories(self):
        """The probe's case: a NULL category and a later "" "all other values" one. QGIS draws NULL and unmatched
        values with the later one (its symbol hash keeps the last category of the value ""), while the legend keys
        name the NULL one: the colour drawn wins and names the item."""
        cats = [("Boring", "Boring", "#df9560"), (None, "", "#e049db"), ("", "all other values", "#123456")]
        st, got = self.read(categorized_renderer("T", cats))
        self.assertEqual([i.label for i in st.items], ["Boring", "(no value)", "all other values"])
        self.assertEqual(got, {"B-1": (0, "#df9560"), "CPT-1": (2, "#123456"), "N-1": (2, "#123456"),
                               "Z-1": (2, "#123456"), "E-1": (2, "#123456")})

    def test_graduated(self):
        _st, got = self.read(QgsGraduatedSymbolRenderer("D", ranges((0, 20, "#fee5d9", "Shallow"),
                                                                    (20, 40, "#fb6a4a", "Deep"))))
        self.assertEqual(got, {"B-1": (0, "#fee5d9"), "CPT-1": (0, "#fee5d9"), "N-1": (1, "#fb6a4a"),
                               "Z-1": (1, "#fb6a4a"), "E-1": (-1, "")})                   # 45: out of every range
        r = self.lyr.renderer()
        r.checkLegendSymbolItem(r.legendSymbolItems()[1].ruleKey(), False)                # a range unticked
        _st, got = self.read()
        self.assertEqual((got["B-1"], got["N-1"], got["Z-1"]), ((0, "#fee5d9"), (-1, ""), (-1, "")))

    def rules(self, with_off=True):
        root = QgsRuleBasedRenderer.Rule(None)
        root.appendChild(QgsRuleBasedRenderer.Rule(marker("#aa0000"), 0, 0, "\"T\" = 'Boring'", "Borings"))
        group = QgsRuleBasedRenderer.Rule(None, 0, 0, "\"T\" IN ('CPT', 'ZZ')", "Group")
        group.appendChild(QgsRuleBasedRenderer.Rule(marker("#00aa00"), 0, 0, "\"T\" = 'CPT'", "CPTs"))
        group.appendChild(QgsRuleBasedRenderer.Rule(marker("#0000aa"), 1000, 5000, "\"T\" = 'ZZ'", "1:1000-1:5000"))
        root.appendChild(group)
        if with_off:
            off = QgsRuleBasedRenderer.Rule(marker("#999999"), 0, 0, "\"Name\" = 'N-1'", "Off rule")
            off.setActive(False)
            root.appendChild(off)
        root.appendChild(QgsRuleBasedRenderer.Rule(marker("#555555"), 0, 0, "ELSE", "Everything else"))
        return QgsRuleBasedRenderer(root)

    def test_rule_based(self):
        """A nested child, a scale-limited rule (every scale counts), the ELSE rule; a feature matched only by an
        inactive rule is not caught by ELSE either (QGIS 4.2.1 does not draw it); without that rule it is."""
        st, got = self.read(self.rules())
        self.assertEqual([i.label for i in st.items], ["Borings", "CPTs", "1:1000-1:5000", "Off rule",
                                                       "Everything else"])
        self.assertEqual(got, {"B-1": (0, "#aa0000"), "CPT-1": (1, "#00aa00"), "Z-1": (2, "#0000aa"),
                               "N-1": (-1, ""), "E-1": (4, "#555555")})
        _st, got = self.read(self.rules(with_off=False))
        self.assertEqual(got["N-1"], (3, "#555555"))
        # a rule unticked in the Layers panel: its explorations are drawn by nothing
        r = self.lyr.renderer()
        r.checkLegendSymbolItem(next(i.ruleKey() for i in r.legendSymbolItems() if i.label() == "Borings"), False)
        _st, got = self.read()
        self.assertEqual(got["B-1"], (-1, ""))

    def test_overlapping_rules_take_the_last(self):
        _st, got = self.read(rule_renderer([("true", "All", "#111111", True), ("\"D\" > 20", "Deep", "#ee00ee", True)]))
        self.assertEqual(got, {"B-1": (0, "#111111"), "CPT-1": (0, "#111111"), "N-1": (1, "#ee00ee"),
                               "Z-1": (1, "#ee00ee"), "E-1": (1, "#ee00ee")})
        _st, got = self.read(rule_renderer([("true", "All", "#111111", True), ("\"D\" > 20", "Deep", "#ee00ee", False)]))
        self.assertEqual(set(got.values()), {(0, "#111111")})                             # inactive: never matches
        root = QgsRuleBasedRenderer.Rule(None)                                             # a parent with a symbol
        parent = QgsRuleBasedRenderer.Rule(marker("#222222"), 0, 0, "", "All explorations")
        parent.appendChild(QgsRuleBasedRenderer.Rule(marker("#ff8800"), 0, 0, "\"D\" > 20", "Deep"))
        root.appendChild(parent)
        _st, got = self.read(QgsRuleBasedRenderer(root))
        self.assertEqual((got["B-1"], got["Z-1"]), ((0, "#222222"), (1, "#ff8800")))

    def test_data_defined_colour(self):
        sym = marker("#808080")
        sym.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.Property.FillColor, QgsProperty.fromField("Col"))
        st, got = self.read(QgsSingleSymbolRenderer(sym))
        self.assertEqual([(i.key, i.color) for i in st.items], [("0", "#808080")])          # the static colour
        self.assertEqual(got, {"B-1": (0, "#ff0000"), "CPT-1": (0, "#00ff00"), "N-1": (0, "#808080"),
                               "Z-1": (0, "#0000ff"), "E-1": (0, "#232323")})               # near white: outline
        cats = categorized_renderer("T", TYPE_CATS)
        first = cats.categories()[0]                       # (held: the symbol belongs to the category copy)
        boring = first.symbol().clone()
        boring.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.Property.FillColor, QgsProperty.fromField("Col"))
        cats.updateCategorySymbol(0, boring)
        _st, got = self.read(cats)
        self.assertEqual((got["B-1"], got["CPT-1"]), ((0, "#ff0000"), (3, "#cec063")))

    def size_legend(self):
        legend = QgsDataDefinedSizeLegend()
        legend.setClasses([QgsDataDefinedSizeLegend.SizeClass(10, "10"), QgsDataDefinedSizeLegend.SizeClass(20, "20")])
        return legend

    def test_a_data_defined_size_legend_is_left_out(self):
        """Its size classes are not symbols of the layer: single symbol, one item (key "0"); the layer's own
        renderer keeps its size legend."""
        sym = marker("#336699")
        sym.setDataDefinedSize(QgsProperty.fromField("D"))
        r = QgsSingleSymbolRenderer(sym)
        r.setDataDefinedSizeLegend(self.size_legend())
        self.lyr.setRenderer(r)
        live = [(i.ruleKey(), i.label()) for i in self.lyr.renderer().legendSymbolItems()]
        self.assertEqual(len(live), 3)                                                      # the title, 10, 20
        st = Y.layer_style(self.lyr)
        self.assertEqual(st, LayerStyle(kind="single", items=[StyleItem("0", "", "#336699", True)]))
        _st, got = self.read()
        self.assertEqual(got, {n: (0, "#336699") for n in NAMES})
        self.assertIsNotNone(self.lyr.renderer().dataDefinedSizeLegend())
        self.assertEqual([(i.ruleKey(), i.label()) for i in self.lyr.renderer().legendSymbolItems()], live)

    def test_a_size_legend_on_categories(self):
        cats = categorized_renderer("T", TYPE_CATS)
        src = marker("#336699")
        src.setDataDefinedSize(QgsProperty.fromField("D"))
        cats.setSourceSymbol(src)
        for i, cat in enumerate(cats.categories()):
            sym = cat.symbol().clone()
            sym.setDataDefinedSize(QgsProperty.fromField("D"))
            cats.updateCategorySymbol(i, sym)
        cats.setDataDefinedSizeLegend(self.size_legend())
        self.lyr.setRenderer(cats)
        self.assertEqual(len(self.lyr.renderer().legendSymbolItems()), 8)                  # 3 size items in front
        st, got = self.read()
        self.assertEqual([i.label for i in st.items], ["Boring", "Monitoring Well", "Test Pit", "CPT", "(no value)"])
        self.assertEqual((got["B-1"], got["CPT-1"], got["N-1"]), ((0, "#df9560"), (3, "#cec063"), (4, "#e049db")))

    def test_only_the_requested_fids(self):
        self.lyr.setRenderer(categorized_renderer("T", TYPE_CATS))
        _st, got = self.read(names=["B-1", "Z-1"])
        self.assertEqual(got, {"B-1": (0, "#df9560"), "Z-1": (4, "#e049db")})
        self.assertEqual(Y.read_styles(self.lyr, [])[1], {})
        st, out = Y.read_styles(self.lyr, [self.fid["B-1"], 9999])                         # not a feature: none
        self.assertEqual(out, {self.fid["B-1"]: (0, "#df9560"), 9999: (-1, "")})

    def test_the_layer_s_own_renderer_is_not_started(self):
        self.lyr.setRenderer(self.rules())
        live = self.lyr.renderer()
        keys = [i.ruleKey() for i in live.legendSymbolItems()]
        with mock.patch.object(live, "startRender") as start, mock.patch.object(live, "stopRender") as stop,                 mock.patch.object(live, "clone", wraps=live.clone) as clone:
            _st, got = self.read()
        self.assertEqual(clone.call_count, 1)                                              # read on a clone
        start.assert_not_called()
        stop.assert_not_called()
        self.assertEqual(got["B-1"], (0, "#aa0000"))
        self.assertIs(self.lyr.renderer(), live)
        self.assertEqual([i.ruleKey() for i in live.legendSymbolItems()], keys)

    def test_wrappers(self):
        d = QgsPointDisplacementRenderer()
        d.setEmbeddedRenderer(categorized_renderer("T", TYPE_CATS))
        _st, got = self.read(d)
        self.assertEqual((got["B-1"], got["N-1"]), ((0, "#df9560"), (4, "#e049db")))
        cats = categorized_renderer("T", TYPE_CATS)
        cats.updateCategoryRenderState(0, False)                                           # Boring unticked
        merged = QgsMergedFeatureRenderer(cats)
        st, got = self.read(merged)
        self.assertEqual(st.kind, "other")
        self.assertEqual((got["B-1"], got["CPT-1"]), ((-1, ""), (3, "#cec063")))           # (its keys: read at 1:1)
        _st, got = self.read(QgsHeatmapRenderer())
        self.assertEqual(set(got.values()), {(-1, "")})


# ===================================================================================================== build
TYPE_WANT = {t: (i, c) for i, (t, _lab, c) in enumerate(TYPE_CATS) if t}


class BuildColorRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        cls.others = make_others_layer()
        cls.supply = make_supply_layer()
        cls.prj.addMapLayers([cls.others, cls.supply])

    def setUp(self):
        self.pts.setRenderer(categorized_renderer("ExploType", TYPE_CATS))
        self.supply.setRenderer(single_renderer("#b7484b"))

    def build(self, rows, **kw):
        s = rows_settings(self.prj, self.dem, self.lines, rows, **kw)
        return build_section(s, self.prj), s

    def test_plotted_and_left_off_hits_get_their_colours(self):
        s = rows_settings(self.prj, self.dem, self.lines, [explo_row(self.pts, look="color")])
        mw1 = next(f.id() for f in self.pts.getFeatures() if f["ExploName"] == "MW-1")
        s.hidden_points = [hidden_key(line_key(s), self.pts.id(), mw1)]
        m = build_section(s, self.prj)
        self.assertEqual([h.label for h in m.left_off], ["MW-1"])
        info = m.point_layers[0]
        self.assertEqual((info.look, info.color), ("color", ""))
        self.assertEqual((info.style.kind, info.style.field), ("categorized", "ExploType"))
        self.assertEqual([(i.label, i.color) for i in info.style.items],
                         [(lab or "(no value)", c) for _v, lab, c in TYPE_CATS])
        self.assertEqual(len(m.hits), 6)
        for h in m.hits + m.left_off:
            self.assertEqual((h.look, h.style_rank, h.color), ("color",) + TYPE_WANT[h.type_value], h.label)
        self.assertEqual({h.type_value for h in m.hits}, {"Boring", "Monitoring Well", "Test Pit", "CPT"})

    def test_rows_of_each_look(self):
        rows = [explo_row(self.pts), others_row(self.others, look="gray"), supply_row(self.supply, look="color")]
        m, _ = self.build(rows)
        self.assertEqual([i.color for i in m.point_layers], ["", LOOK_GRAY, ""])
        self.assertEqual([i.style is None for i in m.point_layers], [True, True, False])
        self.assertEqual(m.point_layers[2].style.items, [StyleItem("0", "", "#b7484b", True)])
        for h in m.hits:
            want = [("black", -1, ""), ("gray", -1, LOOK_GRAY), ("color", 0, "#b7484b")][h.layer_index]
            self.assertEqual((h.look, h.style_rank, h.color), want, h.label)
        self.assertTrue([h for h in m.hits if h.layer_index == 2])

    def test_black_and_gray_rows_never_read_the_style(self):
        with mock.patch("xsections.core.build.read_styles") as rs:
            m, _ = self.build([explo_row(self.pts), others_row(self.others, look="gray"),
                               supply_row(self.supply, look="black")])
        rs.assert_not_called()
        self.assertTrue(m.hits)
        self.assertEqual({h.style_rank for h in m.hits}, {-1})

    def test_a_color_row_reads_its_hits_once(self):
        real = Y.read_styles
        with mock.patch("xsections.core.build.read_styles", side_effect=real) as rs:
            m, _ = self.build([explo_row(self.pts), supply_row(self.supply, look="color")])
        self.assertEqual(rs.call_count, 1)
        layer, fids, project = rs.call_args.args
        self.assertIs(layer, self.supply)
        self.assertIs(project, self.prj)
        self.assertEqual(sorted(fids), sorted(h.fid for h in m.hits if h.layer_index == 1))

    def test_a_color_row_without_explorations_has_its_style(self):
        m, _ = self.build([explo_row(self.pts), supply_row(self.supply, look="color", types=[NO_TYPES])])
        self.assertEqual([h.layer_index for h in m.hits if h.layer_index == 1], [])
        self.assertEqual(m.point_layers[1].style.kind, "single")

    def test_a_style_that_cannot_be_read(self):
        """The row is drawn in black (no colour on its hits), with a warning; the section is still built."""
        with mock.patch("xsections.core.build.read_styles", side_effect=RuntimeError("boom")):
            m, _ = self.build([explo_row(self.pts), supply_row(self.supply, look="color", name="Supply")])
        supply = [h for h in m.hits if h.layer_index == 1]
        self.assertTrue(supply)
        self.assertEqual({(h.look, h.style_rank, h.color) for h in supply}, {("color", -1, "")})
        self.assertIsNone(m.point_layers[1].style)
        self.assertIn("Supply: its style in QGIS could not be read (RuntimeError); its lines are drawn in black.",
                      m.warnings)
        self.assertEqual(len([h for h in m.hits if h.layer_index == 0]), 7)


@timing_test
class ColorBudget(unittest.TestCase):
    """The 3-row build budget of 0.3.3 (dense, others, supply: 1.5 s) with the supply row in Color."""

    @classmethod
    def setUpClass(cls):
        cls.prj, cls.dem, cls.pts, cls.lines = load_project()
        cls.dense = make_dense_layer()
        cls.others = make_others_layer()
        cls.supply = make_supply_layer()
        cls.supply.setRenderer(single_renderer("#b7484b"))
        cls.prj.addMapLayers([cls.dense, cls.others, cls.supply])

    def test_three_row_build_budget(self):
        dense = point_row(self.dense, label_field="ExploName", type_field="ExploType_resolved",
                          top_field="ExploElev", depth_field="ExploDepth")
        s = rows_settings(self.prj, self.dem, self.lines,
                          [dense, others_row(self.others), supply_row(self.supply, in_range=False, look="color")])
        t = time.perf_counter()
        m = build_section(s, self.prj)
        dt = time.perf_counter() - t
        self.assertEqual([i.plotted for i in m.point_layers], [60, 5, 4])
        self.assertEqual({h.color for h in m.hits if h.layer_index == 2}, {"#b7484b"})
        self.assertLessEqual(dt, budget(1.5), f"3-row build took {dt:.3f} s")
        print(f"\n  3-row build (dense, others, supply in Color): {dt:.3f} s")


if __name__ == "__main__":
    unittest.main()
