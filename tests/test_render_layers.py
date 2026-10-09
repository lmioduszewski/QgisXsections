"""0.3.3 render, several exploration layers: looks per row, the legend's layer entries, rows left out of the
elevation range (the frame arrow and its TD), and the notes per row (build spec section 4, tests 9.3)."""
import math
import unittest

from tests.fixtures import CUMBERLAND_AESI, STANDARD_LAYOUT, TYPE_CATS, color_model, start_app

start_app()

import numpy as np                                                    # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg          # noqa: E402
from matplotlib.figure import Figure                                  # noqa: E402
from matplotlib.lines import Line2D                                   # noqa: E402
from matplotlib.text import Annotation                                # noqa: E402

from xsections.core.model import (LOOK_GRAY, POINT_LAYER_DEFAULTS, GroundProfile, Hit, PointLayerInfo,  # noqa: E402
                                  SectionModel, Settings, WaterLevel, clean_point_layer)
from xsections.render import figure as F                              # noqa: E402
from xsections.render import scales as S                              # noqa: E402
from xsections.render.scales import plan                              # noqa: E402

COLOR = "#b5651d"


# ----------------------------------------------------------------------------- hand-made models with rows
def row_info(i, name, look="black", color=COLOR, in_range=True, on=True, **fields):
    """PointLayerInfo of exploration row i (its cleaned row holds `fields`)."""
    row = clean_point_layer(dict(POINT_LAYER_DEFAULTS, layer_id=f"L{i}", look=look, color=color, in_range=in_range,
                                 **fields))
    c = LOOK_GRAY if look == "gray" else (color if look == "color" else "")
    return PointLayerInfo(index=i, layer_id=f"L{i}", name=name, layer_name=name, look=look, color=c,
                          in_range=in_range, on=on, row=row)


def make_hit(label, station, ground, depth, infos=(), row=0, top_d=0.0, type_value="Boring", td=True, fid=None,
             **kw):
    """A Hit of row `row` (look, colour and range from infos[row] when given)."""
    info = infos[row] if row < len(infos) else None
    top = ground + top_d
    bottom = None if depth is None else top - depth
    return Hit(fid=fid if fid is not None else int(station), label=label, type_value=type_value, x=0.0, y=0.0,
               station=station, offset=12.0, side="L", direction="N", ground_at_station=ground,
               ground_at_point=ground, top=top, top_source="field", bottom=bottom,
               total_depth=depth if (td and depth is not None) else None, layer_index=row,
               layer_id=f"L{row}", layer_name=info.name if info else "", look=info.look if info else "black",
               color=info.color if info else "", in_range=info.in_range if info else True, **kw)


def make_model(hits, infos=(), length=3000.0, z=300.0, step=50.0):
    st = list(np.arange(0.0, length, step)) + [length]
    zf = z if callable(z) else (lambda s: z)
    gp = GroundProfile(stations=st, z=[zf(s) for s in st], step=step)
    hits = sorted(hits, key=lambda h: (h.station, h.layer_index, h.label))
    return SectionModel(length=length, vertex_stations=[0.0, length], azimuth=90.0, ground=gp, hits=hits,
                        dem_name="LIDAR", points_name="Explorations", point_layers=list(infos))


def make_settings(**over):
    s = Settings(label_field="ExploName", tolerance_ft=150.0, **STANDARD_LAYOUT)
    for k, v in over.items():
        setattr(s, k, v)
    return s


def drawn(model, settings, dpi=100, index=0):
    p = plan(model, settings)
    fig = Figure(dpi=dpi)
    FigureCanvasAgg(fig)
    F.draw_page(fig, model, settings, p, p.pages[index])
    fig.canvas.draw()
    return fig, p, p.pages[index]


def depth_lines(ax):
    """The top-to-bottom lines: 2-point vertical Line2D at zorder 3.5 without a marker or a gid."""
    return [ln for ln in ax.lines if ln.get_zorder() == 3.5 and ln.get_gid() is None and ln.get_marker() == "None"
            and len(ln.get_xdata()) == 2 and ln.get_xdata()[0] == ln.get_xdata()[1]]


def line_at(ax, station):
    return [ln for ln in depth_lines(ax) if abs(ln.get_xdata()[0] - station) < 1e-9]


def bars_at(ax, station):
    """(y values of the crossbars at `station`)."""
    out = []
    for ln in ax.lines:
        if ln.get_marker() == "_":
            out += [float(y) for x, y in zip(ln.get_xdata(), ln.get_ydata()) if abs(x - station) < 1e-9]
    return out


def texts_by_gid(fig, gid):
    return [t for t in fig.axes[0].texts if t.get_gid() == gid]


def frame_inches(ax):
    """(kx, kz): paper inches per ft of the axes, from its own size (independent of the painter)."""
    fw, fh = ax.figure.get_size_inches()
    pos = ax.get_position()
    x0, x1 = ax.get_xlim()
    z0, z1 = ax.get_ylim()
    return pos.width * fw / (x1 - x0), pos.height * fh / (z1 - z0)


def three_rows():
    return [row_info(0, "Own"), row_info(1, "By others", look="gray"), row_info(2, "Supply", look="color")]


# ----------------------------------------------------------------------------- looks
class Looks(unittest.TestCase):
    def test_line_tick_label_and_td_colours(self):
        infos = three_rows()
        hits = [make_hit("A-1", 800.0, 300.0, 30.0, infos, 0, type_value="Boring"),
                make_hit("O-1", 1400.0, 300.0, 25.0, infos, 1, type_value="Test Pit"),
                make_hit("S-1", 2000.0, 300.0, 35.0, infos, 2, type_value="Well")]
        fig, p, page = drawn(make_model(hits, infos), make_settings())
        ax = fig.axes[0]
        # (0.3.4) Black and Gray lines at the black width, Color lines at the Color width
        for station, color, lw in ((800.0, F.DATA, F.DEPTH_LW), (1400.0, LOOK_GRAY, F.DEPTH_LW),
                                   (2000.0, COLOR, F.DEPTH_COLOR_LW)):
            (ln,) = line_at(ax, station)
            self.assertEqual(ln.get_color(), color)
            self.assertEqual(ln.get_linewidth(), lw)
        bars = [ln for ln in ax.lines if ln.get_marker() == "_"]
        self.assertEqual(sorted(ln.get_color() for ln in bars), sorted([F.DATA, LOOK_GRAY, COLOR]))
        ticks = [ln for ln in ax.lines if ln.get_marker() == "|"]
        self.assertEqual([ln.get_color() for ln in ticks], [F.INK, LOOK_GRAY])   # one per ink, black first
        self.assertEqual([len(ln.get_xdata()) for ln in ticks], [2, 1])          # a Color row's tick is black
        labels = {a.get_text(): a.get_color() for a in ax.texts if isinstance(a, Annotation)
                  and a.get_text() in ("A-1", "O-1", "S-1")}
        self.assertEqual(labels, {"A-1": F.INK, "O-1": LOOK_GRAY, "S-1": F.INK})
        tds = {t.get_text(): t.get_color() for t in texts_by_gid(fig, F.TD_GID)}
        self.assertEqual(tds, {"TD 30'": F.INK, "TD 25'": LOOK_GRAY, "TD 35'": F.INK})
        halos = texts_by_gid(fig, F.TD_HALO_GID)
        self.assertEqual(len(halos), 3)

    def test_first_row_on_top(self):
        infos = [row_info(0, "Own"), row_info(1, "By others", look="gray")]
        hits = [make_hit("B-2", 1000.0, 300.0, 30.0, infos, 0), make_hit("B-2x", 1000.6, 300.0, 40.0, infos, 1),
                make_hit("B-9", 2000.0, 300.0, 30.0, infos, 0)]
        fig, p, page = drawn(make_model(hits, infos), make_settings())
        ax = fig.axes[0]
        order = [ln.get_xdata()[0] for ln in depth_lines(ax)]
        self.assertEqual(order, [1000.6, 1000.0, 2000.0])      # row 1 first (under), then row 0 by station
        self.assertGreater(ax.lines.index(line_at(ax, 1000.0)[0]), ax.lines.index(line_at(ax, 1000.6)[0]))


# ----------------------------------------------------------------------------- legend
class Legend(unittest.TestCase):
    def kinds(self, model, s=None):
        return [(e.kind, e.text) for e in S.legend_entries(model, s or make_settings())]

    def test_layer_entries_only_when_drawn_differently(self):
        one = make_model([make_hit("A-1", 800.0, 300.0, 30.0)], [row_info(0, "Own")])
        self.assertEqual(self.kinds(one), [])
        two_black = [row_info(0, "Own"), row_info(1, "By others")]
        m = make_model([make_hit("A-1", 800.0, 300.0, 30.0, two_black, 0),
                        make_hit("O-1", 1200.0, 300.0, 30.0, two_black, 1)], two_black)
        self.assertEqual(self.kinds(m), [])                                 # all black: the legend is unchanged
        same_colour = [row_info(0, "Own", look="color"), row_info(1, "By others", look="color", color=COLOR.upper())]
        m = make_model([make_hit("A-1", 800.0, 300.0, 30.0, same_colour, 0),
                        make_hit("O-1", 1200.0, 300.0, 30.0, same_colour, 1)], same_colour)
        # (0.3.4) a Color row with coloured lines is always listed (its colours come from its own style)
        self.assertEqual(self.kinds(m), [("layer", "Own"), ("layer", "By others")])
        infos = three_rows()
        m = make_model([make_hit("S-1", 600.0, 300.0, 30.0, infos, 2), make_hit("A-1", 800.0, 300.0, 30.0, infos, 0),
                        make_hit("O-1", 1200.0, 300.0, 30.0, infos, 1)], infos)
        self.assertEqual(self.kinds(m), [("layer", "Own"), ("layer", "By others"), ("layer", "Supply")])  # row order
        self.assertEqual([e.key for e in S.legend_entries(m, make_settings())], [0, 1, 2])
        # a row with nothing on the section is not listed (and does not count as different)
        m = make_model([make_hit("A-1", 800.0, 300.0, 30.0, infos, 0),
                        make_hit("O-1", 1200.0, 300.0, 30.0, infos, 1)], infos)
        self.assertEqual(self.kinds(m), [("layer", "Own"), ("layer", "By others")])
        m = make_model([make_hit("A-1", 800.0, 300.0, 30.0, infos, 0)], infos)
        self.assertEqual(self.kinds(m), [])
        # a row that is off is not listed either
        off = [row_info(0, "Own"), row_info(1, "By others", look="gray", on=False)]
        m = make_model([make_hit("A-1", 800.0, 300.0, 30.0, off, 0), make_hit("O-1", 1200.0, 300.0, 30.0, off, 1)],
                       off)
        self.assertEqual(self.kinds(m), [])

    def test_order_with_types_screens_and_levels(self):
        infos = three_rows()
        a = make_hit("A-1", 800.0, 300.0, 30.0, infos, 0, screen_top=290.0, screen_bottom=280.0,
                     water_levels=[WaterLevel(elev=292.0, kind="measured", source="WL")])
        o = make_hit("O-1", 1200.0, 300.0, 30.0, infos, 1, type_value="Test Pit")
        m = make_model([a, o], infos)
        self.assertEqual(self.kinds(m), [("layer", "Own"), ("layer", "By others"), ("screen", "Screen"),
                                         ("measured", "Water level")])
        self.assertEqual(S.legend_rows(S.legend_entries(m, make_settings()), 6.0, 6.3)[0][0][0], "Legend:")

    def test_swatches_and_margins(self):
        """The plan sizes the bottom margin from the same entries the sheet draws: more rows, more margin, and every
        legend text inside the printer edge."""
        infos = [row_info(0, "Explorations by AESI"), row_info(1, "Explorations by others (consultants)", look="gray"),
                 row_info(2, "Supply wells (Ecology well logs)", look="color")]
        hits = [make_hit("A-1", 600.0, 300.0, 30.0, infos, 0), make_hit("O-1", 1200.0, 300.0, 30.0, infos, 1),
                make_hit("S-1", 1800.0, 300.0, 30.0, infos, 2)]
        model = make_model(hits, infos, length=2000.0)
        s = make_settings(compact_layout=True, h_scale=200.0, v_scale=20.0, sheet="custom")
        plain = make_model([make_hit("A-1", 600.0, 300.0, 30.0)], [row_info(0, "Own")], length=2000.0)
        p, p0 = plan(model, s), plan(plain, s)
        mg = S.margins(s, (p.z_min, p.z_max), S.legend_entries(model, s))
        mg0 = S.margins(s, (p0.z_min, p0.z_max), S.legend_entries(plain, s))
        self.assertGreater(mg["bottom"], mg0["bottom"])
        self.assertAlmostEqual(p.pages[0].plot_bottom - p0.pages[0].plot_bottom, mg["bottom"] - mg0["bottom"],
                               delta=0.26)      # (custom pages round up to 0.25 in)
        fig, p, page = drawn(model, s, dpi=150)
        r = fig.canvas.get_renderer()
        edge = S.edge_in(s) * fig.dpi
        names = [t for t in fig.texts if t.get_text() in [i.name for i in infos]]
        self.assertEqual(len(names), 3)
        for t in names:
            self.assertGreaterEqual(t.get_window_extent(r).y0, edge - 1.0, t.get_text())
        swatches = [a for a in fig.artists if isinstance(a, Line2D) and a.get_gid() == F.LEGEND_LINE_GID]
        self.assertEqual(sorted(a.get_color() for a in swatches), sorted([F.DATA, LOOK_GRAY, COLOR]))
        widths = {a.get_color(): a.get_linewidth() for a in swatches}       # (0.3.4) as the lines are drawn
        self.assertEqual([widths[c] for c in (F.DATA, LOOK_GRAY, COLOR)], [F.DEPTH_LW, F.DEPTH_LW, F.DEPTH_COLOR_LW])


# ----------------------------------------------------------------------------- Color rows (0.3.4)
def styled(hits, infos, row=0, cats=TYPE_CATS, kind="categorized", **kw):
    """make_model(hits, infos, **kw) with row `row` drawn in Color from a style of `cats` (fixtures.color_model)."""
    return color_model(make_model(hits, infos, **kw), row, cats, kind)


def swatches_of(fig):
    return [a for a in fig.artists if isinstance(a, Line2D) and a.get_gid() == F.LEGEND_LINE_GID]


class ColorLayers(unittest.TestCase):
    """A Color row (decision 23): each exploration's line in its symbol's colour at the Color width, names, ticks
    and TD black; the legend lists the colours drawn, named as the layer's legend names them."""

    def kinds(self, model, s=None):
        return [(e.kind, e.text, e.color) for e in S.legend_entries(model, s or make_settings())]

    def test_lines_in_each_hits_colour(self):
        infos = [row_info(0, "Own", look="color")]
        hits = [make_hit("B-1", 600.0, 300.0, 30.0, infos, 0, type_value="Boring"),
                make_hit("M-1", 1000.0, 300.0, 30.0, infos, 0, type_value="Monitoring Well", top_d=-20.0),
                make_hit("X-1", 1400.0, 300.0, 30.0, infos, 0, type_value="Vapor Probe")]     # no symbol
        model = styled(hits, infos)
        self.assertEqual([(h.label, h.style_rank, h.color) for h in model.hits],
                         [("B-1", 0, "#df9560"), ("M-1", 1, "#3fcaa2"), ("X-1", -1, "")])
        fig, p, page = drawn(model, make_settings())
        ax = fig.axes[0]
        for station, color, lw in ((600.0, "#df9560", F.DEPTH_COLOR_LW), (1000.0, "#3fcaa2", F.DEPTH_COLOR_LW),
                                   (1400.0, F.DATA, F.DEPTH_LW)):           # no symbol: as Black
            (ln,) = line_at(ax, station)
            self.assertEqual((ln.get_color(), ln.get_linewidth()), (color, lw), station)
        # the bars take the line's colour and width (M-1's top is off the ground: a top cap too)
        bars = [ln for ln in ax.lines if ln.get_marker() == "_"]
        got = sorted((float(ln.get_xdata()[0]), len(ln.get_xdata()), ln.get_color(), ln.get_markeredgewidth())
                     for ln in bars)
        self.assertEqual(got, [(600.0, 1, "#df9560", F.DEPTH_COLOR_LW), (1000.0, 2, "#3fcaa2", F.DEPTH_COLOR_LW),
                               (1400.0, 1, F.DATA, F.DEPTH_LW)])
        # the dotted link from the ground to M-1's top in its colour (0.6 pt as always)
        links = [ln for ln in ax.lines if ln.get_zorder() == 3.4]
        self.assertEqual([(ln.get_color(), ln.get_linewidth()) for ln in links], [("#3fcaa2", 0.6)])
        # names, ticks and TD black: one tick call for all three
        ticks = [ln for ln in ax.lines if ln.get_marker() == "|"]
        self.assertEqual([(ln.get_color(), len(ln.get_xdata())) for ln in ticks], [(F.INK, 3)])
        labels = {a.get_text(): a.get_color() for a in ax.texts if isinstance(a, Annotation)
                  and a.get_text() in ("B-1", "M-1", "X-1")}
        self.assertEqual(labels, {"B-1": F.INK, "M-1": F.INK, "X-1": F.INK})
        self.assertEqual({t.get_color() for t in texts_by_gid(fig, F.TD_GID)}, {F.INK})
        self.assertEqual(len(texts_by_gid(fig, F.TD_GID)), 3)

    def test_the_arrow_of_a_clipped_color_hit(self):
        infos = [row_info(0, "Own"), row_info(1, "Supply", look="color", in_range=False)]
        hits = [make_hit("A-1", 600.0, 300.0, 30.0, infos, 0),
                make_hit("HW-1", 1000.0, 300.0, 400.0, infos, 1, type_value="Monitoring Well")]
        model = styled(hits, infos, row=1, length=2000.0)
        fig, p, page = drawn(model, make_settings(h_scale=200.0, v_scale=20.0), dpi=150)
        ax = fig.axes[0]
        (ln,) = line_at(ax, 1000.0)
        self.assertEqual((ln.get_color(), ln.get_linewidth(), ln.get_ydata()[1]),
                         ("#3fcaa2", F.DEPTH_COLOR_LW, p.z_min))
        (arrow,) = [a for a in ax.lines if a.get_gid() == F.CLIP_GID]
        self.assertEqual((arrow.get_color(), arrow.get_linewidth()), ("#3fcaa2", F.DEPTH_COLOR_LW))
        (td,) = texts_by_gid(fig, F.CLIP_TD_GID)
        self.assertEqual((td.get_text(), td.get_color()), ("TD 400'", F.INK))

    def test_a_lone_color_row_lists_its_categories_in_legend_order(self):
        infos = [row_info(0, "Own", look="color")]
        hits = [make_hit("C-1", 400.0, 300.0, 30.0, infos, 0, type_value="CPT"),
                make_hit("B-1", 800.0, 300.0, 30.0, infos, 0, type_value="Boring"),
                make_hit("X-1", 1000.0, 300.0, 30.0, infos, 0, type_value="Vapor Probe"),    # no symbol: not listed
                make_hit("M-1", 1200.0, 300.0, 30.0, infos, 0, type_value="Monitoring Well"),
                make_hit("B-2", 1600.0, 300.0, 30.0, infos, 0, type_value="Boring")]
        model = styled(hits, infos)
        self.assertEqual(self.kinds(model), [("style", "Boring", "#df9560"), ("style", "Monitoring Well", "#3fcaa2"),
                                             ("style", "CPT", "#cec063")])      # the style's order, not by station
        self.assertEqual({e.key for e in S.legend_entries(model, make_settings())}, {0})
        # the blank category is named as the layer's legend names it
        blank = styled(hits + [make_hit("N-1", 2000.0, 300.0, 30.0, infos, 0, type_value="")], infos)
        self.assertEqual(self.kinds(blank)[-1], ("style", "(no value)", "#e049db"))
        # the depth lines off: nothing is drawn in colour, nothing listed
        self.assertEqual(self.kinds(model, make_settings(depth_line=False)), [])
        # explorations without a bottom draw no line: they add no colour
        flat = styled([make_hit("B-1", 800.0, 300.0, None, infos, 0, type_value="Boring"),
                       make_hit("M-1", 1200.0, 300.0, 30.0, infos, 0, type_value="Monitoring Well")], infos)
        self.assertEqual(self.kinds(flat), [("style", "Monitoring Well", "#3fcaa2")])
        # on the sheet: "Legend:", the labels, one swatch per entry in its colour at the Color width
        s = make_settings(compact_layout=True, h_scale=200.0, v_scale=20.0)
        fig, p, page = drawn(model, s)
        texts = [t.get_text() for t in fig.texts]
        for t in ("Legend:", "Boring", "Monitoring Well", "CPT"):
            self.assertIn(t, texts)
        self.assertEqual([(a.get_color(), a.get_linewidth()) for a in swatches_of(fig)],
                         [("#df9560", F.DEPTH_COLOR_LW), ("#3fcaa2", F.DEPTH_COLOR_LW), ("#cec063", F.DEPTH_COLOR_LW)])

    def test_identical_items_merge_and_a_label_in_two_colours_stays_twice(self):
        cats = [("EB", "EB, B", "#df9560"), ("B", "EB, B", "#df9560"),             # the same label and colour
                ("IT1", "IT", "#7f74df"), ("IT2", "IT", "#6fdd54")]                 # Tehaleh: two "IT" rules
        infos = [row_info(0, "Own", look="color")]
        hits = [make_hit(f"X-{i}", 300.0 + 300.0 * i, 300.0, 30.0, infos, 0, type_value=t)
                for i, t in enumerate(["IT2", "B", "EB", "IT1"])]
        model = styled(hits, infos, cats=cats, kind="rule")
        self.assertEqual(self.kinds(model), [("style", "EB, B", "#df9560"), ("style", "IT", "#7f74df"),
                                             ("style", "IT", "#6fdd54")])

    def test_two_color_rows_of_one_style_list_each_colour_once(self):
        # his own explorations and those by others share one categorized style (Cumberland), and a project saved
        # with Data lines "By type" opens with both rows in Color: a label and colour is listed once, where it
        # first comes (row order, then the legend's); the same label in another colour is still listed twice
        infos = [row_info(0, "Own", look="color"), row_info(1, "By others", look="color")]
        hits = [make_hit("B-1", 400.0, 300.0, 30.0, infos, 0, type_value="Boring"),
                make_hit("M-1", 800.0, 300.0, 30.0, infos, 0, type_value="Monitoring Well"),
                make_hit("T-9", 1200.0, 300.0, 30.0, infos, 1, type_value="Test Pit"),
                make_hit("M-9", 1600.0, 300.0, 30.0, infos, 1, type_value="Monitoring Well"),
                make_hit("B-9", 2000.0, 300.0, 30.0, infos, 1, type_value="Boring")]
        model = color_model(styled(hits, infos), 1)
        want = [("style", 0, "Boring", "#df9560"), ("style", 0, "Monitoring Well", "#3fcaa2"),
                ("style", 1, "Test Pit", "#80a7ea")]
        self.assertEqual([(e.kind, e.key, e.text, e.color) for e in S.legend_entries(model, make_settings())], want)
        # on the sheet: one swatch and one label each, and the margins of one row listing the same three colours
        s = make_settings(compact_layout=True, h_scale=200.0, v_scale=20.0)
        fig, p, page = drawn(model, s)
        self.assertEqual([(a.get_color(), a.get_linewidth()) for a in swatches_of(fig)],
                         [(c, F.DEPTH_COLOR_LW) for *_k, c in want])
        texts = [t.get_text() for t in fig.texts]
        self.assertEqual([texts.count(t) for t in ("Boring", "Monitoring Well", "Test Pit")], [1, 1, 1])
        alone = styled([make_hit(h.label, h.station, 300.0, 30.0, infos, 0, type_value=h.type_value) for h in hits],
                       infos[:1])
        self.assertEqual([e.text for e in S.legend_entries(alone, s)], [t for *_k, t, _c in want])
        self.assertEqual(S.margins(s, (p.z_min, p.z_max), S.legend_entries(model, s)),
                         S.margins(s, (p.z_min, p.z_max), S.legend_entries(alone, s)))
        # the other row's style draws "Monitoring Well" in another colour (as Tehaleh's rules can): listed twice
        blue = [(v, lab, "#2323ff" if v == "Monitoring Well" else c) for v, lab, c in TYPE_CATS]
        model = color_model(styled(hits, infos), 1, blue)
        self.assertEqual([(e.key, e.text, e.color) for e in S.legend_entries(model, make_settings())],
                         [(0, "Boring", "#df9560"), (0, "Monitoring Well", "#3fcaa2"),
                          (1, "Monitoring Well", "#2323ff"), (1, "Test Pit", "#80a7ea")])

    def test_single_symbol_is_the_row_name(self):
        infos = [row_info(0, "Own"), row_info(1, "Supply wells", look="color")]
        hits = [make_hit("A-1", 600.0, 300.0, 30.0, infos, 0),
                make_hit("HW-1", 1000.0, 300.0, 30.0, infos, 1, type_value=""),
                make_hit("HW-2", 1400.0, 300.0, 30.0, infos, 1, type_value="")]
        model = styled(hits, infos, row=1, cats=[(None, "", "#b7484b")], kind="single")
        # Black + Color: the Black row by name, the single-symbol row by name with its symbol's colour
        self.assertEqual(self.kinds(model), [("layer", "Own", ""), ("layer", "Supply wells", "#b7484b")])
        fig, p, page = drawn(model, make_settings(compact_layout=True, h_scale=200.0, v_scale=20.0))
        self.assertEqual(sorted((a.get_color(), a.get_linewidth()) for a in swatches_of(fig)),
                         sorted([(F.DATA, F.DEPTH_LW), ("#b7484b", F.DEPTH_COLOR_LW)]))
        # alone it is still listed (its colour says what the lines are)
        alone = styled([make_hit("HW-1", 1000.0, 300.0, 30.0, infos[1:], 0, type_value="")],
                       [row_info(0, "Supply wells", look="color")], cats=[(None, "", "#b7484b")], kind="single")
        self.assertEqual(self.kinds(alone), [("layer", "Supply wells", "#b7484b")])

    def test_a_color_row_drawn_all_black_counts_as_black(self):
        infos = [row_info(0, "Own"), row_info(1, "By others", look="color")]
        hits = [make_hit("A-1", 600.0, 300.0, 30.0, infos, 0),
                make_hit("O-1", 1000.0, 300.0, 30.0, infos, 1, type_value="Vapor Probe")]   # no symbol
        self.assertEqual(self.kinds(styled(hits, infos, row=1)), [])
        gray = [row_info(0, "Own", look="gray"), row_info(1, "By others", look="color")]
        hits = [make_hit("A-1", 600.0, 300.0, 30.0, gray, 0),
                make_hit("O-1", 1000.0, 300.0, 30.0, gray, 1, type_value="Vapor Probe")]
        self.assertEqual(self.kinds(styled(hits, gray, row=1)), [("layer", "Own", ""), ("layer", "By others", "")])

    def test_entries_do_not_depend_on_the_frame_and_size_the_margins(self):
        infos = [row_info(0, "Own", look="color"), row_info(1, "Supply", look="gray", in_range=False)]
        many = [make_hit(f"X-{i}", 200.0 + 200.0 * i, 300.0, 30.0, infos, 0, type_value=v)
                for i, (v, _lab, _c) in enumerate(CUMBERLAND_AESI[:12])]
        many.append(make_hit("HW-1", 2800.0, 300.0, 400.0, infos, 1))
        model = styled(many, infos, cats=CUMBERLAND_AESI)
        one = styled(many[:1] + many[-1:], infos, cats=CUMBERLAND_AESI)
        for s in (make_settings(compact_layout=True), make_settings(show_notes=False), make_settings()):
            p = plan(model, s)
            self.assertEqual(S.legend_entries(model, s), S.legend_entries(model, s, p.z_min, p.z_max))
            self.assertEqual(len([e for e in S.legend_entries(model, s) if e.kind == "style"]), 12)
            if s.compact_layout or not s.show_notes:
                mg = S.margins(s, (p.z_min, p.z_max), S.legend_entries(model, s))
                p1 = plan(one, s)
                mg1 = S.margins(s, (p1.z_min, p1.z_max), S.legend_entries(one, s))
                self.assertGreater(mg["bottom"], mg1["bottom"])
                self.assertGreaterEqual(p.pages[0].plot_bottom, mg["bottom"] - 1e-9)

    def test_depth_widths_from_sheet_style(self):
        infos = [row_info(0, "Own"), row_info(1, "By others", look="gray"), row_info(2, "Supply", look="color")]
        hits = [make_hit("A-1", 600.0, 300.0, 30.0, infos, 0), make_hit("O-1", 1200.0, 300.0, 30.0, infos, 1),
                make_hit("S-1", 1800.0, 300.0, 30.0, infos, 2, type_value="Boring")]
        model = styled(hits, infos, row=2, length=2000.0)
        s = make_settings(compact_layout=True, h_scale=200.0, v_scale=20.0, depth_lw_black=1.0, depth_lw_color=2.25)
        fig, p, page = drawn(model, s)
        ax = fig.axes[0]
        for station, color, lw in ((600.0, F.DATA, 1.0), (1200.0, LOOK_GRAY, 1.0), (1800.0, "#df9560", 2.25)):
            (ln,) = line_at(ax, station)
            self.assertEqual((ln.get_color(), ln.get_linewidth()), (color, lw))     # Gray at the black width
            (bar,) = [b for b in ax.lines if b.get_marker() == "_" and b.get_xdata()[0] == station]
            self.assertEqual((bar.get_color(), bar.get_markeredgewidth()), (color, lw))
        self.assertEqual(sorted((a.get_color(), a.get_linewidth()) for a in swatches_of(fig)),
                         sorted([(F.DATA, 1.0), (LOOK_GRAY, 1.0), ("#df9560", 2.25)]))
        # widths out of their range are clamped, not drawn as given
        wild = make_settings(compact_layout=True, h_scale=200.0, v_scale=20.0, depth_lw_black=9.0, depth_lw_color=0.0)
        fig, p, page = drawn(model, wild)
        self.assertEqual(line_at(fig.axes[0], 600.0)[0].get_linewidth(), 3.0)
        self.assertEqual(line_at(fig.axes[0], 1800.0)[0].get_linewidth(), 0.25)


# ----------------------------------------------------------------------------- the elevation range
class Range(unittest.TestCase):
    """A row left out of the elevation range: it never widens the frame; deeper explorations stop at the frame
    with an arrow and their TD."""

    def setUp(self):
        self.infos = [row_info(0, "Own"), row_info(1, "Supply", in_range=False)]
        self.s = make_settings(h_scale=200.0, v_scale=20.0)

    def deep_model(self, **kw):
        hits = [make_hit("A-1", 600.0, 300.0, 30.0, self.infos, 0), make_hit("A-2", 1400.0, 300.0, 25.0, self.infos, 0),
                make_hit("HW-1", 1000.0, 300.0, 400.0, self.infos, 1, **kw),
                make_hit("HW-2", 1800.0, 300.0, 20.0, self.infos, 1)]
        return make_model(hits, self.infos, length=2000.0)

    def test_runs_below_rule(self):
        s = self.s
        h = make_hit("HW-1", 1000.0, 300.0, 400.0, self.infos, 1)
        self.assertTrue(S.runs_below(h, 200.0, s))
        self.assertFalse(S.runs_below(make_hit("A", 1000.0, 300.0, 400.0, self.infos, 0), 200.0, s))   # in range
        self.assertFalse(S.runs_below(h, 200.0, make_settings(depth_line=False)))
        self.assertFalse(S.runs_below(make_hit("X", 1000.0, 300.0, 100.0, self.infos, 1), 200.0, s))   # at the frame
        self.assertFalse(S.runs_below(make_hit("Y", 1000.0, 300.0, 50.0, self.infos, 1), 200.0, s))    # above it
        self.assertTrue(S.hit_in_range(object()))                    # anything without the field is in range

    def test_out_of_range_row_leaves_the_range_alone(self):
        model = self.deep_model()
        without = make_model([h for h in model.hits if h.layer_index == 0], self.infos[:1], length=2000.0)
        p, p0 = plan(model, self.s), plan(without, self.s)
        self.assertEqual(p.z_min, p0.z_min)
        self.assertEqual(p.lowest_what, "the bottom of A-1")          # names in-range data only
        self.assertEqual(p.lowest_what, p0.lowest_what)
        self.assertEqual(p.warnings, [])
        # in range it would widen the frame down to its bottom
        inside = make_model([make_hit(h.label, h.station, 300.0, 400.0 if h.label == "HW-1" else
                                      h.top - h.bottom) for h in model.hits], length=2000.0)
        self.assertLess(plan(inside, self.s).z_min, -100.0)
        # its levels and screens add nothing either
        wet = self.deep_model(screen_top=150.0, screen_bottom=100.0,
                              water_levels=[WaterLevel(elev=120.0, kind="atd", source="ATD")])
        self.assertEqual(plan(wet, self.s).z_min, p0.z_min)
        # a manual range does not report out-of-range bottoms as cut off
        manual = make_settings(h_scale=200.0, v_scale=20.0, z_mode="manual", z_min=200.0, z_max=360.0)
        self.assertEqual(plan(self.deep_model(), manual).warnings, [])

    def test_arrow_td_and_no_bottom_bar(self):
        model = self.deep_model()
        fig, p, page = drawn(model, self.s, dpi=150)
        ax = fig.axes[0]
        z0 = p.z_min
        (ln,) = line_at(ax, 1000.0)
        self.assertEqual(list(ln.get_ydata()), [300.0, z0])             # ends exactly at the frame
        self.assertEqual(ln.get_color(), F.DATA)
        self.assertEqual(bars_at(ax, 1000.0), [])                       # no bottom bar (and no top cap: on the ground)
        arrows = [a for a in ax.lines if a.get_gid() == F.CLIP_GID]
        self.assertEqual(len(arrows), 1)
        kx, kz = frame_inches(ax)
        xs, ys = np.asarray(arrows[0].get_xdata(), float), np.asarray(arrows[0].get_ydata(), float)
        self.assertAlmostEqual((ys[1] - z0) * kz, S.CLIP_ARROW_TIP_IN, places=9)       # the tip just above
        self.assertAlmostEqual((ys[0] - z0) * kz, S.CLIP_ARROW_TIP_IN + S.CLIP_ARROW_H_IN, places=9)
        self.assertAlmostEqual((xs[2] - xs[0]) / 2 * kx, S.CLIP_ARROW_HALF_IN, places=9)
        self.assertEqual(xs[1], 1000.0)
        self.assertEqual((arrows[0].get_linewidth(), arrows[0].get_color()), (F.DEPTH_LW, F.DATA))
        self.assertEqual(arrows[0].get_solid_joinstyle(), "miter")
        (td,) = texts_by_gid(fig, F.CLIP_TD_GID)
        self.assertEqual(td.get_text(), "TD 400'")
        self.assertEqual((td.get_ha(), td.get_va()), ("left", "baseline"))
        x, y = td.get_position()
        self.assertAlmostEqual((x - 1000.0) * kx, S.CLIP_TD_DX_IN, places=9)
        self.assertAlmostEqual((y - z0) * kz, S.CLIP_TD_BASE_IN, places=9)
        bb = td.get_window_extent(fig.canvas.get_renderer())
        frame = ax.get_window_extent()
        self.assertTrue(frame.x0 < bb.x0 and bb.x1 < frame.x1 and frame.y0 < bb.y0 and bb.y1 < frame.y1)
        self.assertEqual(len(texts_by_gid(fig, F.CLIP_TD_HALO_GID)), 1)
        self.assertNotIn("TD 400'", [t.get_text() for t in texts_by_gid(fig, F.TD_GID)])
        # the shallower one of the same row is drawn whole, with its bar and its TD label under it
        (whole,) = line_at(ax, 1800.0)
        self.assertEqual(list(whole.get_ydata()), [300.0, 280.0])
        self.assertEqual(bars_at(ax, 1800.0), [280.0])
        self.assertIn("TD 20'", [t.get_text() for t in texts_by_gid(fig, F.TD_GID)])

    def test_td_with_td_labels_off_and_the_notes(self):
        s = make_settings(h_scale=200.0, v_scale=20.0, td_label=False)
        model = self.deep_model()
        fig, p, page = drawn(model, s)
        self.assertEqual([t.get_text() for t in texts_by_gid(fig, F.CLIP_TD_GID)], ["TD 400'"])
        self.assertEqual(texts_by_gid(fig, F.TD_GID), [])
        sentence = "An arrow at the bottom of the frame: the exploration goes deeper; its TD is beside the arrow."
        note3 = F.notes_text(model, s, p, page)[1][0]
        self.assertIn(sentence, note3)
        self.assertIn("TD = total depth.", note3)                       # the clipped TD is a TD on the sheet
        line2 = F.compact_notes(model, s, p, page)[1]
        self.assertIn(F.NotePart("Arrow at frame bottom: deeper, TD beside it", 0), line2)
        self.assertIn(F.NotePart("TD = total depth"), line2)
        # without a clipped well: neither
        shallow = make_model([h for h in model.hits if h.label != "HW-1"], self.infos, length=2000.0)
        p2 = plan(shallow, s)
        self.assertNotIn("An arrow", F.notes_text(shallow, s, p2, p2.pages[0])[1][0])
        self.assertNotIn("Arrow at frame bottom", " ".join(n.text for n in F.compact_notes(shallow, s, p2,
                                                                                          p2.pages[0])[1]))
        self.assertNotIn("TD = total depth", F.notes_text(shallow, s, p2, p2.pages[0])[1][0])

    def test_levels_below_the_frame_are_not_drawn(self):
        model = self.deep_model(water_levels=[WaterLevel(elev=280.0, kind="atd", source="ATD"),
                                              WaterLevel(elev=100.0, kind="atd", source="ATD")],
                                screen_top=120.0, screen_bottom=110.0)
        fig, p, page = drawn(model, self.s)
        ax = fig.axes[0]
        atd = [a for a in ax.patches if a.get_gid() == F.ATD_GID]
        self.assertEqual(len(atd), 1)                                   # only the one inside the frame
        self.assertGreater(min(y for _, y in atd[0].get_xy()), p.z_min)
        self.assertEqual([a for a in ax.lines if a.get_gid() == F.SCREEN_GID], [])   # the screen is below it

    def test_legend_and_notes_leave_out_what_the_frame_cuts(self):
        """(FIX 0.3.3) The levels and screens of a row out of the range that lie below the frame are not drawn, with
        a line down there or not (no depth; Depth line off), and neither the legend nor the notes list them; the
        in-range row's are listed as always. The plan, made before the frame is known, counts them all."""
        infos = [row_info(0, "Own", wl_field="WL"),
                 row_info(1, "Supply", in_range=False, atd_field="ATD", screen_top_field="ST", screen_bottom_field="SB")]
        own = make_hit("A-1", 600.0, 300.0, 30.0, infos, 0,
                       water_levels=[WaterLevel(elev=290.0, kind="measured", source="WL")])
        deep = make_hit("HW-1", 1000.0, 300.0, 400.0, infos, 1, screen_top=120.0, screen_bottom=110.0,
                        water_levels=[WaterLevel(elev=100.0, kind="atd", source="ATD")])
        bare = make_hit("HW-2", 1400.0, 300.0, None, infos, 1,
                        water_levels=[WaterLevel(elev=120.0, kind="atd", source="ATD")])
        model = make_model([own, deep, bare], infos, length=2000.0)
        self.assertTrue({"screen", "measured", "atd"} <= {e.kind for e in S.legend_entries(model, self.s)})
        for s in (self.s, make_settings(h_scale=200.0, v_scale=20.0, depth_line=False),
                  make_settings(h_scale=200.0, v_scale=20.0, compact_layout=True)):
            fig, p, page = drawn(model, s)
            ax = fig.axes[0]
            self.assertGreater(p.z_min, 120.0)
            self.assertEqual([a for a in ax.patches if a.get_gid() == F.ATD_GID], [])
            self.assertEqual([a for a in ax.lines if a.get_gid() == F.SCREEN_GID], [])
            self.assertEqual(len([a for a in ax.patches if a.get_gid() == F.WL_GID]), 1)      # A-1's
            texts = [t.get_text() for t in fig.texts]
            self.assertNotIn("Water at time of drilling (ATD)", texts)
            self.assertNotIn("Screen", texts)
            self.assertIn("Water level", texts)
            notes = " ".join(texts)
            self.assertNotIn("(ATD)", notes)
            self.assertNotIn("ST to SB", notes)
            self.assertIn("ater levels: WL", notes)

    def test_clipped_tds_side_by_side_and_at_the_right_edge(self):
        infos = self.infos
        hits = [make_hit("A-1", 600.0, 300.0, 30.0, infos, 0),
                make_hit("HW-1", 1000.0, 300.0, 400.0, infos, 1), make_hit("HW-2", 1010.0, 300.0, 380.0, infos, 1),
                make_hit("HW-3", 1995.0, 300.0, 390.0, infos, 1)]
        fig, p, page = drawn(make_model(hits, infos, length=2000.0), self.s, dpi=150)
        ax = fig.axes[0]
        kx, kz = frame_inches(ax)
        tds = {t.get_text(): t for t in texts_by_gid(fig, F.CLIP_TD_GID)}
        self.assertEqual(sorted(tds), ["TD 380'", "TD 390'", "TD 400'"])
        rows = {k: abs(round(((t.get_position()[1] - p.z_min) * kz - S.CLIP_TD_BASE_IN) / S.TD_ROW_IN, 6))
                for k, t in tds.items()}
        # (FIX 0.3.3) HW-2's arrow is 10 ft (0.05 in) right of HW-1: HW-1's TD goes on the other side of its line
        # rather than over that arrow, and HW-2's stays on its row, right of its line
        self.assertEqual(rows, {"TD 400'": 0.0, "TD 380'": 0.0, "TD 390'": 0.0})
        self.assertEqual((tds["TD 400'"].get_ha(), tds["TD 380'"].get_ha()), ("right", "left"))
        self.assertAlmostEqual((1000.0 - tds["TD 400'"].get_position()[0]) * kx, S.CLIP_TD_DX_IN, places=9)
        r = fig.canvas.get_renderer()
        arrows = [a.get_window_extent(r) for a in ax.lines if a.get_gid() == F.CLIP_GID]
        self.assertEqual(len(arrows), 3)
        for t in tds.values():                                          # no TD covers an arrow
            b = t.get_window_extent(r)
            for a in arrows:
                self.assertFalse(min(a.x1, b.x1) > max(a.x0, b.x0) and min(a.y1, b.y1) > max(a.y0, b.y0),
                                 t.get_text())
        edge = tds["TD 390'"]                                           # 5 ft from the right end: left of its line
        self.assertEqual(edge.get_ha(), "right")
        self.assertAlmostEqual((1995.0 - edge.get_position()[0]) * kx, S.CLIP_TD_DX_IN, places=9)
        r = fig.canvas.get_renderer()
        frame = ax.get_window_extent()
        boxes = [t.get_window_extent(r) for t in tds.values()]
        for b in boxes:
            self.assertTrue(frame.x0 <= b.x0 and b.x1 <= frame.x1, b)
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(min(a.x1, b.x1) > max(a.x0, b.x0) and min(a.y1, b.y1) > max(a.y0, b.y0))

    def test_side_labels_keep_clear_or_are_named(self):
        """(FIX 0.3.3) Six wells of a row out of the range, 12 ft apart (the reviewer's well field): the TD labels with
        no row under their bars go beside their lines only where they clear every other TD label and every bar; one
        with no such spot is left out, and the plan names it."""
        infos = self.infos
        hits = [make_hit("A-1", 600.0, 300.0, 30.0, infos, 0)]
        for i in range(6):
            hits.append(make_hit(f"W-{i + 1}", 1500.0 + 12.0 * i, 300.0, 31.0 + i, infos, 1))
        model = make_model(hits, infos, length=2000.0)
        fig, p, page = drawn(model, self.s, dpi=150)
        ax = fig.axes[0]
        r = fig.canvas.get_renderer()
        tds = texts_by_gid(fig, F.TD_GID) + texts_by_gid(fig, F.CLIP_TD_GID)
        boxes = [(t.get_text(), t.get_window_extent(r)) for t in tds]

        def overlap(a, b, tol=0.5):
            return min(a.x1, b.x1) - max(a.x0, b.x0) > tol and min(a.y1, b.y1) - max(a.y0, b.y0) > tol
        for i, (na, a) in enumerate(boxes):
            for nb, b in boxes[i + 1:]:
                self.assertFalse(overlap(a, b), f"{na} over {nb}")
        from matplotlib.transforms import Bbox
        dpi = fig.dpi
        for h in model.hits:                                            # every bottom bar stays in sight
            x, y = ax.transData.transform((h.station, h.bottom))
            bar = Bbox.from_extents(x - S.CROSSBAR_IN / 2 * dpi, y - S.BAR_CLEAR_IN / 2 * dpi,
                                    x + S.CROSSBAR_IN / 2 * dpi, y + S.BAR_CLEAR_IN / 2 * dpi)
            for name, b in boxes:
                self.assertFalse(overlap(bar, b), f"{name} over the bar of {h.label}")
        shown = {t.get_text() for t in tds}
        missing = [h.label for h in model.hits if S.td_text(h.total_depth) not in shown]
        self.assertTrue(len(shown) >= 4, shown)
        for label in missing:
            self.assertIn(label, " ".join(p.warnings))
        self.assertEqual(bool(missing), any("No room for the TD label" in w for w in p.warnings))

    def test_td_labels_follow_the_plan(self):
        """td_labels(..., label_hits) lays out those labels only, with every hit's bars and marks in their way; the
        sheet puts each in-range TD label at or above the row the plan reserved for it (a mixed model)."""
        s = make_settings(h_scale=200.0, v_scale=20.0)
        infos = self.infos
        a = make_hit("A", 1000.0, 300.0, 40.0, infos, 0)
        o = make_hit("O", 1015.0, 300.0, 41.0, infos, 1)                # its bar lies on A's row 0
        b = make_hit("B", 1030.0, 300.0, 42.0, infos, 0)
        model = make_model([a, o, b], infos, length=2000.0)
        alone = S.td_labels([a], s, 2000.0)
        self.assertAlmostEqual(alone[0][1], 260.0 - (S.TD_GAP_IN + S.TD_TEXT_H_IN) * 20.0, places=9)   # row 0
        got = S.td_labels(model.hits, s, 2000.0, model.ground, label_hits=[a])
        self.assertEqual([h.label for h, _ in got], ["A"])
        self.assertLess(got[0][1], alone[0][1] - S.TD_ROW_IN * 20.0 + 1e-6)                # dropped by O's bar
        p = plan(model, s)
        reach = dict((h.label, r) for h, r in S.td_labels(model.hits, s, p.plot_length, model.ground,
                                                          label_hits=[h for h in model.hits if h.in_range]))
        self.assertEqual(sorted(reach), ["A", "B"])
        fig, p, page = drawn(model, s, dpi=150)
        drawn_td = {t.get_text(): t.get_position()[1] for t in texts_by_gid(fig, F.TD_GID)}
        self.assertEqual(sorted(drawn_td), ["TD 40'", "TD 41'", "TD 42'"])
        for label, text in (("A", "TD 40'"), ("B", "TD 42'")):
            bottom = drawn_td[text] - S.TD_TEXT_H_IN * s.v_scale
            self.assertGreaterEqual(bottom, reach[label] - 1e-6, label)

    def test_out_of_range_label_without_a_row_goes_beside_its_line(self):
        """An out-of-range exploration drawn whole whose TD label has no row inside the frame: beside its line,
        centred on its bottom bar, kept inside the frame."""
        infos = self.infos
        s = make_settings(h_scale=200.0, v_scale=20.0, z_mode="manual", z_min=260.0, z_max=320.0)
        hits = [make_hit("A", 600.0, 300.0, 20.0, infos, 0), make_hit("HW", 1000.0, 300.0, 39.0, infos, 1)]
        fig, p, page = drawn(make_model(hits, infos, length=2000.0), s)
        ax = fig.axes[0]
        kx, kz = frame_inches(ax)
        side = [t for t in texts_by_gid(fig, F.TD_GID) if t.get_text() == "TD 39'"]
        self.assertEqual(len(side), 1)
        t = side[0]
        self.assertEqual((t.get_ha(), t.get_va()), ("left", "center"))
        self.assertAlmostEqual((t.get_position()[0] - 1000.0) * kx, S.CLIP_TD_DX_IN, places=9)
        self.assertAlmostEqual((t.get_position()[1] - 260.0) * kz, max(1.0 * kz, 0.01 + S.TD_TEXT_H_IN / 2), places=9)

    def test_built_rows(self):
        """Built from layers: a supply row out of the range leaves the frame as the other rows set it; HW-1
        (400 ft deep) runs below it with its arrow; the row's lines are in its colour."""
        from tests.fixtures import load_project, make_supply_layer, point_row, single_renderer, TOLERANCE
        from xsections.core.build import build_section
        prj, dem, pts, lines = load_project()
        supply = make_supply_layer()
        supply.setRenderer(single_renderer(COLOR))                 # (0.3.4) Color: the colour of the layer's style
        prj.addMapLayers([supply])
        own = point_row(layer=pts, label_field="ExploName", type_field="ExploType", top_field="ExploElev",
                        depth_field="ExploDepth")
        wells = point_row(layer=supply, label_field="AESI_MapLabel", type_field="ExploType_resolved",
                          top_field="ExploElev", depth_field="WellCompleteDepth", atd_field="GW_Elev_ATD",
                          in_range=False, look="color", color=COLOR)
        base = dict(line_layer_id=lines.id(), line_fid=next(lines.getFeatures()).id(), dem_layer_id=dem.id(),
                    tolerance_ft=TOLERANCE, h_scale=500.0, v_scale=50.0, **STANDARD_LAYOUT)
        s = Settings(point_layers=[own, wells], **base)
        s0 = Settings(point_layers=[own], **base)
        m, m0 = build_section(s, prj), build_section(s0, prj)
        p, p0 = plan(m, s), plan(m0, s0)
        self.assertEqual(p.z_min, p0.z_min)
        self.assertEqual(p.lowest_what, p0.lowest_what)
        below = [h.label for h in m.hits if S.runs_below(h, p.z_min, s)]
        self.assertIn("HW-1", below)
        fig, p, page = drawn(m, s)
        ax = fig.axes[0]
        hw1 = next(h for h in m.hits if h.label == "HW-1")
        (ln,) = line_at(ax, hw1.station)
        self.assertEqual((ln.get_color(), ln.get_ydata()[1]), (COLOR, p.z_min))
        self.assertEqual(len([a for a in ax.lines if a.get_gid() == F.CLIP_GID]), len(below))
        self.assertIn("TD 400'", [t.get_text() for t in texts_by_gid(fig, F.CLIP_TD_GID)])
        self.assertEqual([e.text for e in S.legend_entries(m, s) if e.kind == "layer"], ["Explorations",
                                                                                        "Supply wells"])


# ----------------------------------------------------------------------------- notes per row
class NotesPerRow(unittest.TestCase):
    def notes(self, infos, hits, s=None):
        s = s or make_settings()
        model = make_model(hits, infos)
        p = plan(model, s)
        page = p.pages[0]
        return F.notes_text(model, s, p, page)[1][0], F.compact_notes(model, s, p, page)[1], model

    def test_identical_fields_read_as_today(self):
        fields = dict(top_field="ExploElev", depth_field="ExploDepth")
        infos = [row_info(0, "Own", **fields), row_info(1, "By others", look="gray", **fields)]
        hits = [make_hit("A-1", 800.0, 300.0, 30.0, infos, 0), make_hit("O-1", 1400.0, 300.0, 25.0, infos, 1)]
        note3, line2, model = self.notes(infos, hits)
        self.assertIn("Tops: ExploElev where available, otherwise LIDAR at the exploration. Bottoms: top minus "
                      "ExploDepth. TD = total depth.", note3)                                   # test_e2e's sentence
        self.assertIn(F.NotePart("Tops: ExploElev, else LIDAR", 2), line2)                       # test_layout's
        self.assertIn(F.NotePart("Bottoms: top − ExploDepth", 2), line2)
        self.assertEqual([n for n, _ in F.layer_views(model, make_settings())], ["Own", "By others"])
        # the shared settings' flat keys play no part: each row's view names its fields
        self.assertEqual(F.layer_views(model, make_settings())[1][1].depth_field, "ExploDepth")

    def test_different_fields_name_the_rows(self):
        infos = [row_info(0, "Own", top_field="ExploElev", depth_field="ExploDepth"),
                 row_info(1, "Supply", look="color", depth_field="WellCompleteDepth"),
                 row_info(2, "By others", look="gray", top_field="ExploElev", depth_field="ExploDepth"),
                 row_info(3, "Unused", top_field="Elev", bottom_elev_field="Bot")]          # nothing plotted: not named
        hits = [make_hit("A-1", 800.0, 300.0, 30.0, infos, 0), make_hit("S-1", 1400.0, 300.0, 45.0, infos, 1),
                make_hit("O-1", 2000.0, 300.0, 25.0, infos, 2)]
        note3, line2, model = self.notes(infos, hits)
        self.assertIn("Tops: ExploElev where available, otherwise LIDAR at the exploration in Own and By others; "
                      "LIDAR at the exploration in Supply. Bottoms: top minus ExploDepth in Own and By others; top "
                      "minus WellCompleteDepth in Supply. TD = total depth.", note3)
        self.assertIn(F.NotePart("Tops: ExploElev, else LIDAR (Own and By others); LIDAR (Supply)", 2), line2)
        self.assertIn(F.NotePart("Bottoms: top − ExploDepth (Own and By others); top − WellCompleteDepth (Supply)",
                                 2), line2)
        self.assertNotIn("Unused", note3)
        # three names: "A, B and C"; a row without bottom fields adds no bottoms text
        views = [("A", make_settings(top_field="T")), ("B", make_settings(top_field="T")),
                 ("C", make_settings(top_field="T")), ("D", make_settings())]
        self.assertEqual(F.depth_sources_text(make_settings(), False, views),
                         "Tops: T where available, otherwise LIDAR at the exploration in A, B and C; LIDAR at the "
                         "exploration in D.")
        self.assertEqual(F.depth_sources_short(make_settings(), views), ["Tops: T, else LIDAR (A, B and C); LIDAR (D)"])
        # called without views: exactly today's text
        flat = make_settings(top_field="ExploElev", bottom_elev_field="BotElev", depth_field="ExploDepth")
        self.assertEqual(F.depth_sources_text(flat, True), "Tops: ExploElev where available, otherwise LIDAR at the "
                         "exploration. Bottoms: BotElev where available, otherwise top minus ExploDepth. TD = total "
                         "depth.")
        self.assertEqual(F.depth_sources_short(flat), ["Tops: ExploElev, else LIDAR",
                                                       "Bottoms: BotElev, else top − ExploDepth"])

    def test_screens_and_levels_per_row(self):
        infos = [row_info(0, "Own", screen_top_field="ScrTop", screen_bottom_field="ScrBot", wl_field="WL_Elev"),
                 row_info(1, "Supply", screen_top_field="SCR_T", screen_bottom_field="SCR_B",
                          screen_values="elevation", wl_table_id="tbl")]
        a = make_hit("A-1", 800.0, 300.0, 30.0, infos, 0, screen_top=290.0, screen_bottom=280.0,
                     water_levels=[WaterLevel(elev=295.0, kind="measured", source="WL_Elev")])
        b = make_hit("S-1", 1400.0, 300.0, 45.0, infos, 1, screen_top=270.0, screen_bottom=260.0,
                     water_levels=[WaterLevel(elev=280.0, kind="atd", source="table")])
        model = make_model([a, b], infos)
        s = make_settings()
        self.assertEqual(F.screens_sources(model, s),
                         "Screens: ScrTop to ScrBot (depths below the top) in Own; SCR_T to SCR_B (elevations) in "
                         "Supply; water levels: WL_Elev in Own; a table of water levels in Supply")
        same = [row_info(0, "Own", screen_top_field="ScrTop", screen_bottom_field="ScrBot", wl_field="WL_Elev"),
                row_info(1, "By others", screen_top_field="ScrTop", screen_bottom_field="ScrBot", wl_field="WL_Elev")]
        a2 = make_hit("A-1", 800.0, 300.0, 30.0, same, 0, screen_top=290.0, screen_bottom=280.0,
                      water_levels=[WaterLevel(elev=295.0, kind="measured", source="WL_Elev")])
        b2 = make_hit("O-1", 1400.0, 300.0, 45.0, same, 1)
        self.assertEqual(F.screens_sources(make_model([a2, b2], same), s),
                         "Screens: ScrTop to ScrBot (depths below the top); water levels: WL_Elev")
        # a model made by hand without rows reads the flat settings, as before
        flat = make_model([make_hit("A-1", 800.0, 300.0, 30.0, screen_top=290.0, screen_bottom=280.0)])
        self.assertEqual(F.layer_views(flat, s), [("", s)])
        self.assertEqual(F.screens_sources(flat, make_settings(screen_top_field="T", screen_bottom_field="B")),
                         "Screens: T to B (depths below the top)")


class StandardBlock(unittest.TestCase):
    """(FIX 0.3.3) The standard layout's notes and legend under the plot: three rows that differ, screens and levels,
    the colours of a Color row's style and four Other points rows make a long block; the bottom margin grows to hold it, so its
    lowest mark stays inside the printer edge (the margin stays MARGIN when the block fits)."""

    @staticmethod
    def model():
        from tests.test_other_points_render import other_info, other_point
        infos = [row_info(0, "Explorations by AESI (geotechnical borings, 2003 to 2025)", top_field="ExploElev",
                          depth_field="ExploDepth", wl_field="DepthToGW", wl_values="depth", screen_top_field="ScrTop",
                          screen_bottom_field="ScrBot"),
                 row_info(1, "Explorations by others (consultants and agencies)", look="gray", depth_field="ExploDepth",
                          wl_field="GW_Elev"),
                 row_info(2, "Supply wells (Ecology well logs, all statuses)", look="color",
                          depth_field="WellCompleteDepth", atd_field="GW_Elev_ATD", screen_top_field="SCR_T",
                          screen_bottom_field="SCR_B", screen_values="elevation")]
        types = ["BORING", "MONITORING WELL", "TEST PIT", "CPT", "EXPLORATION PIT", "HAND AUGER", "PIEZOMETER", "WELL"]
        hits = [make_hit(f"A-{i}", 200.0 + 150.0 * i, 300.0, 30.0, infos, 0, type_value=t, screen_top=290.0,
                         screen_bottom=280.0, water_levels=[WaterLevel(elev=292.0, kind="measured", source="DepthToGW")])
                for i, t in enumerate(types)]
        hits.append(make_hit("O-1", 1700.0, 300.0, 25.0, infos, 1, type_value="Boring",
                             water_levels=[WaterLevel(elev=290.0, kind="measured", source="GW_Elev")]))
        hits.append(make_hit("S-1", 2000.0, 300.0, 35.0, infos, 2, type_value="Domestic", screen_top=285.0,
                             screen_bottom=280.0, water_levels=[WaterLevel(elev=288.0, kind="atd", source="GW_Elev_ATD")]))
        m = make_model(hits, infos, length=3000.0)
        m.other_layers = [other_info(0, "Springs (USGS)", elev="lidar"),
                          other_info(1, "Wetland seeps", elev="field", elev_field="Elev_ft"),
                          other_info(2, "Seeps mapped 2025 (field crew)", shape="triangle", color="#c2185b"),
                          other_info(3, "Spring boxes (county)", shape="square", color="#2e8b57", elev="field",
                                     elev_field="WS_Elev", elev_empty="lidar")]
        m.other_points = [other_point(f"P-{j}", 2300.0 + 150.0 * j, 300.0, j=j, name=m.other_layers[j].name)
                          for j in range(4)]
        return m

    def lowest(self, model, s):
        """(the lowest mark drawn on the sheet, paper inches from its bottom edge; the plan)"""
        fig, p, page = drawn(model, s, dpi=150)
        r = fig.canvas.get_renderer()
        lows = ([t.get_window_extent(r).y0 for t in fig.texts if t.get_text()]
                + [a.get_window_extent(r).y0 for a in fig.artists])
        return min(lows) / fig.dpi, p

    def test_the_block_stays_inside_the_printer_edge(self):
        model = self.model()
        # (0.3.4) the first row drawn in Color, one category per type: its colours make the legend long
        types = [h.type_value for h in model.hits if h.layer_index == 0]
        color_model(model, 0, [(t, t, c) for t, (_v, _lab, c) in zip(types, CUMBERLAND_AESI)])
        for h, v in ((600.0, 100.0), (500.0, 100.0)):
            for edge in (0.5, 0.3):
                s = make_settings(h_scale=h, v_scale=v, sheet="letter", compact_layout=False,
                                  show_notes=True, fill_grid="off", edge_margin_in=edge)
                low, p = self.lowest(model, s)
                self.assertGreaterEqual(low, edge - 1e-3, f"{h}/{v}, edge {edge}: {p.pages[0].sheet_name}")
        # a short block: the bottom margin is MARGIN, as before
        plain = make_model([make_hit("A-1", 600.0, 300.0, 30.0)], [row_info(0, "Own")], length=3000.0)
        s = make_settings(h_scale=600.0, v_scale=100.0, sheet="letter", compact_layout=False, show_notes=True)
        p = plan(plain, s)
        mg = S.margins(s, (p.z_min, p.z_max), S.legend_entries(plain, s))
        self.assertEqual(mg["bottom"], S.MARGIN["bottom"])
        self.assertEqual(p.pages[0].plot_bottom, S._place(p.pages[0].page_w, p.pages[0].page_h, p.pages[0].plot_w,
                                                           p.pages[0].plot_h, mg)[1])


if __name__ == "__main__":
    unittest.main()
