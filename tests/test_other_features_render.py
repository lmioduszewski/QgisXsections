"""0.3.6 Other features, the render part (build spec section 5, tests 8.3): a line row's crossings drawn as its symbol
resting on the ground line; a polygon row's pieces as brackets (a line with end ticks over the piece, its label
centred above it) inside the frame above the ground and the labels under them, or in a band of rows above the frame
(the top margin grows); stacking (the longer piece above), open ends past A or A′ ("(continues)"), edge lines, the
legend, Auto and Manual elevations, tiles and the preview. Checked on the drawn artists, independently of the
painter where it matters; sheets without line or polygon rows are drawn exactly as before (scales.area_layout [])."""
import dataclasses
import math
import unittest

from tests.fixtures import STANDARD_LAYOUT, start_app

start_app()

import numpy as np                                                    # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg          # noqa: E402
from matplotlib.colors import to_hex                                  # noqa: E402
from matplotlib.figure import Figure                                  # noqa: E402
from matplotlib.lines import Line2D                                   # noqa: E402

from tests.test_figure import make_model as hits_model                # noqa: E402
from tests.test_layout import furniture, ink_in_edge, overlapping     # noqa: E402
from tests.test_other_points_render import GAP, by_gid, clearance, frame_inches, ground_of  # noqa: E402
from xsections.core.model import (OTHER_POINT_DEFAULTS, AreaPiece, OtherLayerInfo, OtherPoint,  # noqa: E402
                                  SectionModel, Settings, clean_other_point, feature_row)
from xsections.render import figure as F                              # noqa: E402
from xsections.render import scales as S                              # noqa: E402
from xsections.render.scales import plan                              # noqa: E402

PURPLE, GREEN, BROWN, BLUE = "#7a4fb0", "#2e7d32", "#8c5a3c", "#1f6fb2"
LENGTH = 4470.0                     # the hits model's length: its plot length rounds up (to 4,480 ft at 400 ft per inch)
MANUAL_MAX = 300.0                  # a manual maximum (a whole major) over the ground with no room for the Sites


# ----------------------------------------------------------------------------- hand-made rows
def area_info(j, name, color=PURPLE, bracket="inside", style="solid", edges="off"):
    row = feature_row("polygon", layer_id=f"A{j}", name=name, color=color, bracket=bracket, bracket_style=style,
                      edges=edges)
    return OtherLayerInfo(index=j, layer_id=f"A{j}", name=name, layer_name=name, shape="asterisk", color=color,
                          size=7.0, elev="line", elev_field="", elev_empty="line", on=True, row=row, kind="polygon",
                          bracket=bracket, bracket_style=style, edges=edges)


def line_info(j, name="Streams", shape="stream", color=BLUE, size=7.0):
    row = feature_row("line", layer_id=f"L{j}", name=name, shape=shape, color=color, size=size)
    return OtherLayerInfo(index=j, layer_id=f"L{j}", name=name, layer_name=name, shape=shape, color=color, size=size,
                          elev="line", elev_field="", elev_empty="line", on=True, row=row, kind="line")


def point_info(j, name="Seeps", shape="asterisk", color=BLUE, size=7.0):
    row = clean_other_point(dict(OTHER_POINT_DEFAULTS, layer_id=f"P{j}", name=name, shape=shape, color=color))
    return OtherLayerInfo(index=j, layer_id=f"P{j}", name=name, layer_name=name, shape=shape, color=color, size=size,
                          elev="line", elev_field="", elev_empty="line", on=True, row=row)


def piece(j, start, end, label="", name="", open_start=False, open_end=False):
    return AreaPiece(fid=int(start) + 1, label=label, type_value="", start=start, end=end, open_start=open_start,
                     open_end=open_end, layer_index=j, layer_id=f"A{j}", layer_name=name)


def crossing(label, station, ground, j, name="Streams"):
    gs = ground.z_at(station)
    return OtherPoint(fid=int(station), label=label, type_value="", x=0.0, y=0.0, station=station, offset=0.0, side="",
                      direction="", ground_at_station=gs, ground_at_point=gs, z=gs, how="line", layer_index=j,
                      layer_id=f"L{j}", layer_name=name, kind="crossing")


def seep(label, station, ground, j, name="Seeps"):
    gs = ground.z_at(station)
    return OtherPoint(fid=int(station), label=label, type_value="", x=0.0, y=0.0, station=station, offset=20.0,
                      side="L", direction="N", ground_at_station=gs, ground_at_point=gs, z=gs, how="line",
                      layer_index=j, layer_id=f"P{j}", layer_name=name)


def with_rows(model, infos, points=(), pieces=()):
    """`model` with these Other features rows (their index = their place), points and pieces, sorted as built."""
    model.other_layers = list(infos)
    model.other_points = sorted(points, key=lambda p: (p.station, p.layer_index, p.label))
    model.other_areas = sorted(pieces, key=lambda a: (a.start, a.layer_index, a.label))
    return model


def site_model(edges="off", parcels="inside", lots_style="solid"):
    """The hits model (explorations with vertical labels, a bend at 2,600 ft, a DEM gap) with a seep, a stream
    crossed twice and three polygon rows: Sites (Project site 1,000-2,000 ft with Wetland A 1,200-1,500 ft inside
    it), Lots (two disjoint pieces, one without a label) and Parcels (open past A and past A′)."""
    m = hits_model(length=LENGTH)
    g = m.ground
    infos = [point_info(0), line_info(1), area_info(2, "Sites", edges=edges),
             area_info(3, "Lots", GREEN, style=lots_style), area_info(4, "Parcels", BROWN, bracket=parcels)]
    points = [seep("S-1", 1700.0, g, 0), crossing("Clover Cr.", 900.0, g, 1), crossing("Clover Cr.", 1350.0, g, 1)]
    pieces = [piece(2, 1000.0, 2000.0, "Project site", "Sites"), piece(2, 1200.0, 1500.0, "Wetland A", "Sites"),
              piece(3, 3000.0, 3200.0, "Lot 1", "Lots"), piece(3, 3700.0, 3900.0, "", "Lots"),
              piece(4, 0.0, 300.0, "Parcel A", "Parcels", open_start=True),
              piece(4, 4300.0, LENGTH, "Parcel Z", "Parcels", open_end=True)]
    return with_rows(m, infos, points, pieces)


def settings(**over):
    s = Settings(label_field="ExploName", type_field="ExploType", tolerance_ft=150.0, h_scale=400.0, v_scale=50.0,
                 **STANDARD_LAYOUT)
    for k, v in over.items():
        setattr(s, k, v)
    return s


def drawn(model, s, dpi=100, index=0, p=None):
    p = p or plan(model, s)
    fig = Figure(dpi=dpi)
    FigureCanvasAgg(fig)
    F.draw_page(fig, model, s, p, p.pages[index])
    fig.canvas.draw()
    return fig, p


class Bracket:
    """The artists of one drawn bracket (AREA_GID lines of one height and colour), in data units."""

    def __init__(self, line):
        self.line, self.ticks, self.arrows = line, [], []
        self.y = float(line.get_ydata()[0])
        self.a, self.b = sorted(float(v) for v in line.get_xdata())
        self.color = to_hex(line.get_color())


def brackets(ax):
    """The drawn brackets of `ax`: each horizontal AREA_GID line with the ticks and arrows that meet it."""
    arts = [a for a in ax.lines if a.get_gid() == F.AREA_GID]
    out = []
    for a in arts:
        xs, ys = np.asarray(a.get_xdata(), float), np.asarray(a.get_ydata(), float)
        if len(xs) == 2 and ys[0] == ys[1]:
            out.append(Bracket(a))
    for a in arts:
        xs, ys = np.asarray(a.get_xdata(), float), np.asarray(a.get_ydata(), float)
        if len(xs) == 2 and ys[0] == ys[1]:
            continue
        for b in out:
            if to_hex(a.get_color()) != b.color:
                continue
            if len(xs) == 2 and xs[0] == xs[1] and min(ys) < b.y < max(ys) and b.a - 1e-9 <= xs[0] <= b.b + 1e-9:
                b.ticks.append(a)
                break
            if len(xs) == 3 and ys[1] == b.y and xs[1] in (b.a, b.b):
                b.arrows.append(a)
                break
    return out


def dashes(line):
    """A drawn line's dash pattern in pt (matplotlib scales it by the width: the painter divided it first)."""
    offset, seq = line._dash_pattern
    return (round(offset, 9), [round(v, 9) for v in seq] if seq is not None else None)


def label_texts(ax, gid=F.AREA_LABEL_GID):
    return [t for t in ax.texts if t.get_gid() == gid]


def band_labels(fig):
    """(name, window extent) of the bracket labels over the frame (tests.test_layout.furniture's form)."""
    r = fig.canvas.get_renderer()
    top = fig.axes[0].get_window_extent(r).y1
    return [(f"bracket {t.get_text()}", t.get_window_extent(r)) for t in label_texts(fig.axes[0])
            if t.get_window_extent(r).y0 >= top - 0.5]


def px_box(fig, art):
    bb = art.get_window_extent(fig.canvas.get_renderer())
    return bb.x0, bb.x1, bb.y0, bb.y1


# ----------------------------------------------------------------------------- crossings (line rows)
class CrossingsOnTheSheet(unittest.TestCase):
    def model(self):
        g = ground_of(lambda st: 300.0 + 0.03 * st)
        m = SectionModel(length=3000.0, vertex_stations=[0.0, 3000.0], azimuth=90.0, ground=g, hits=[],
                         dem_name="LIDAR", points_name="", has_explorations=False)
        return with_rows(m, [line_info(0)], [crossing("Clover Cr.", 1000.0, g, 0), crossing("Mill Cr.", 2000.0, g, 0)])

    def test_resting_and_labelled_by_name(self):
        m = self.model()
        for s in (settings(h_scale=200.0, v_scale=20.0), settings(h_scale=200.0, v_scale=20.0, label_offset=True)):
            fig, p = drawn(m, s)
            ax = fig.axes[0]
            arts = by_gid(ax, F.OTHER_GID)
            self.assertEqual(len(arts), 4)                                   # two strokes per stream symbol
            for station in (1000.0, 2000.0):                                 # each symbol's lowest ink on the line
                mine = [a for a in arts if abs(float(np.mean(a.get_xdata())) - station) < 50.0]
                self.assertEqual(len(mine), 2)
                cs = [clearance(a, ax) for a in mine]
                self.assertGreaterEqual(min(cs), -1e-5)
                self.assertLessEqual(min(cs), GAP + 1e-4)
            self.assertEqual(sorted(t.get_text() for t in by_gid(ax, F.OTHER_LABEL_GID)), ["Clover Cr.", "Mill Cr."])
            self.assertEqual(S.display_label(m.other_points[0], s), "Clover Cr.")
        self.assertEqual(S.legend_entries(m, s), [S.LegendEntry("Streams", "point", 0)])
        self.assertTrue([a for a in fig.artists if a.get_gid() == F.LEGEND_SYMBOL_GID])

    def test_notes(self):
        m = self.model()
        s = settings(h_scale=200.0, v_scale=20.0)
        p = plan(m, s)
        note = F.note_texts(m, s, p, p.pages[0])[1]
        self.assertIn(" Streams where they cross the section line: on the ground line.", note)
        self.assertNotIn("Streams within", note)
        sc = settings(h_scale=200.0, v_scale=20.0, compact_layout=True)
        self.assertIn(F.NotePart("Streams: on the ground line", 3), F.compact_notes(m, sc, p, p.pages[0])[1])
        # a point row keeps its sentence
        m.other_layers[0] = dataclasses.replace(m.other_layers[0], kind="point")
        self.assertIn(" Streams within 150 ft of the section line: on the ground line.",
                      F.note_texts(m, s, p, p.pages[0])[1])


# ----------------------------------------------------------------------------- brackets inside the frame
class BracketsInside(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = site_model()
        cls.s = settings()
        cls.fig, cls.p = drawn(cls.model, cls.s)
        cls.ax = cls.fig.axes[0]
        cls.spots = S.area_layout(cls.model, cls.s, cls.p.plot_length, z_cap=cls.p.z_max)

    def spot(self, text):
        return next(sp for sp in self.spots if sp.text == text)

    def test_one_bracket_per_piece_with_its_label(self):
        bs = brackets(self.ax)
        self.assertEqual(len(bs), 6)
        self.assertEqual(sorted(t.get_text() for t in label_texts(self.ax)),
                         sorted(["Project site", "Wetland A", "Lot 1", "Lots", "Parcel A (continues)",
                                 "Parcel Z (continues)"]))                   # a blank label: the row's legend name
        self.assertEqual(len(label_texts(self.ax, F.AREA_LABEL_HALO_GID)), 6)
        for t in label_texts(self.ax):
            self.assertEqual((t.get_ha(), t.get_va(), t.get_fontsize(), t.get_zorder(), t.get_clip_on()),
                             ("center", "bottom", S.LABEL_PT, 6, False))
        colours = {b.a: b.color for b in bs}
        self.assertEqual((colours[1000.0], colours[3000.0], colours[0.0]), (PURPLE, GREEN, BROWN))
        for t in label_texts(self.ax):                                        # labels in the row's colour
            self.assertIn(to_hex(t.get_color()), (PURPLE, GREEN, BROWN))
        for b in bs:
            self.assertEqual((b.line.get_linewidth(), b.line.get_zorder(), b.line.get_solid_capstyle()),
                             (S.AREA_LW, F.AREA_Z, "butt"))

    def test_clear_of_the_ground_and_the_labels_under_them(self):
        """Every tick bottom stands AREA_CLEAR_IN above the ground stroke and every exploration tick and label,
        crossing, seep and label under the bracket's footprint (the line and its drawn label), in sheet paper
        inches (independently of area_layout: the obstacles as scales lays them out, the brackets as drawn)."""
        v, hs = self.s.v_scale, self.s.h_scale
        frame_w = self.p.plot_length / hs
        top = S.ground_top_fn(self.model.ground.stations, self.model.ground.z, lambda st: st / hs, lambda z: z / v)
        symbols, labels = S.other_label_boxes(self.model, self.s, self.p.plot_length)
        obstacles = (S.mark_obstacles(S.marks_on_paper(self.model.hits, self.s, frame_w), self.s.label_vertical)
                     + symbols + labels)
        x0 = self.ax.get_xlim()[0]
        ax_left = self.ax.get_window_extent(self.fig.canvas.get_renderer()).x0
        texts = {t.get_text(): t for t in label_texts(self.ax)}
        bs = brackets(self.ax)
        for sp in self.spots:
            b = next(br for br in bs if br.y == sp.line_z)                    # drawn at the layout's height
            t = texts[sp.text]
            l_px, r_px, _, _ = px_box(self.fig, t)
            left = min(b.a / hs, (l_px - ax_left) / self.fig.dpi + x0 / hs)  # the drawn bracket and its label
            right = max(b.b / hs, (r_px - ax_left) / self.fig.dpi + x0 / hs)
            under = max([top(left, right)] + [bt for bl, br, _bb, bt in obstacles if bl < right and left < br])
            self.assertTrue(b.ticks or b.arrows, sp.text)
            for tick in b.ticks:
                bottom = min(tick.get_ydata()) / v
                self.assertGreaterEqual(bottom, under + S.AREA_CLEAR_IN - 1e-6, sp.text)
            self.assertGreaterEqual(b.y / v - S.AREA_TICK_IN, under + S.AREA_CLEAR_IN - 1e-6, sp.text)
        # and the drawn labels: no bracket label overlaps an exploration's or a point's
        others = [a for a in self.ax.texts if a.get_text() and a.get_gid() not in (F.AREA_LABEL_GID,
                                                                                  F.AREA_LABEL_HALO_GID)]
        for t in label_texts(self.ax):
            a = px_box(self.fig, t)
            for o in others:
                bb = px_box(self.fig, o)
                if bb[1] - bb[0] <= 0:
                    continue
                self.assertFalse(min(a[1], bb[1]) - max(a[0], bb[0]) > 0.5 and min(a[3], bb[3]) - max(a[2], bb[2]) > 0.5,
                                 f"{t.get_text()!r} overlaps {o.get_text()!r}")

    def test_the_longer_piece_above(self):
        site, wet = self.spot("Project site"), self.spot("Wetland A")
        self.assertGreater(site.level, wet.level)
        self.assertEqual(wet.level, 0)
        v = self.s.v_scale
        b = {round(br.a): br for br in brackets(self.ax)}
        site_bottom = min(min(t.get_ydata()) for t in b[1000].ticks) / v
        self.assertGreaterEqual(site_bottom, wet.top_z / v + S.AREA_STACK_GAP_IN - 1e-9)
        self.assertGreater(site.line_z, wet.top_z)
        lot1, lot2 = self.spot("Lot 1"), self.spot("Lots")                   # apart: the same level
        self.assertEqual((lot1.level, lot2.level), (0, 0))
        self.assertEqual([sp.lowered for sp in self.spots], [False] * 6)

    def test_open_ends_and_ticks_at_true_ends_only(self):
        bs = {round(b.a): b for b in brackets(self.ax)}
        pa, pz = bs[0], bs[4300]
        self.assertEqual((len(pa.arrows), len(pa.ticks)), (1, 1))
        tip = pa.arrows[0]
        self.assertEqual(float(tip.get_xdata()[1]), 0.0)                      # the tip at A
        self.assertGreater(min(tip.get_xdata()), -1e-9)                       # pointing left: its arms to the right
        self.assertEqual(float(pa.ticks[0].get_xdata()[0]), 300.0)            # the tick at its true end only
        self.assertEqual(tip.get_solid_joinstyle(), "miter")
        self.assertEqual((len(pz.arrows), len(pz.ticks)), (1, 1))
        self.assertEqual(float(pz.arrows[0].get_xdata()[1]), LENGTH)          # A′: the line's length ...
        self.assertNotEqual(LENGTH, self.p.plot_length)                       # ... not the plot length
        self.assertLess(max(pz.arrows[0].get_xdata()), LENGTH + 1e-9)
        self.assertEqual(pz.b, LENGTH)
        self.assertEqual(float(pz.ticks[0].get_xdata()[0]), 4300.0)
        for key in (1000, 1200, 3000, 3700):                                  # closed pieces: two ticks, no arrow
            self.assertEqual((len(bs[key].ticks), len(bs[key].arrows)), (2, 0), key)
        x0, z0, kx, kz = frame_inches(self.ax)
        for b in bs.values():
            for t in b.ticks:                                                 # from half the line's width above
                ys = t.get_ydata()
                self.assertAlmostEqual((ys[0] - b.y) * kz, S.AREA_LW / 144.0, places=9)
                self.assertAlmostEqual((b.y - ys[1]) * kz, S.AREA_TICK_IN, places=9)

    def test_line_styles_and_edge_lines(self):
        self.assertEqual(by_gid(self.ax, F.AREA_EDGE_GID), [])               # off by default
        m = site_model(edges="ground", lots_style="dash")
        m.other_layers[3] = dataclasses.replace(m.other_layers[3], edges="full")
        fig, p = drawn(m, self.s)
        ax = fig.axes[0]
        bs = {round(b.a): b for b in brackets(ax)}
        self.assertEqual(dashes(bs[3000].line), (0.0, [4.0, 2.0]))     # dashed: 4 / 2 pt whatever the width
        self.assertEqual(bs[1000].line.get_linestyle(), "-")
        for t in bs[3000].ticks:
            self.assertEqual(t.get_linestyle(), "-")                          # ticks stay solid
        edges = by_gid(ax, F.AREA_EDGE_GID)
        self.assertEqual(len(edges), 8)                                       # Sites and Lots: 2 x 2 pieces x 2 ends
        for e in edges:
            xs, ys = e.get_xdata(), e.get_ydata()
            self.assertEqual(xs[0], xs[1])
            self.assertEqual((e.get_linewidth(), dashes(e), e.get_zorder()), (0.6, (0.0, [3.0, 2.0]), F.AREA_EDGE_Z))
            b = next(br for br in bs.values() if br.y == ys[0] and br.a <= xs[0] <= br.b)
            if b.color == PURPLE:                                             # to the ground (in a DEM gap: the
                g = m.ground.z_at(xs[0])                                      # nearest valid ground; 2,000 ft is)
                self.assertAlmostEqual(ys[1], g if math.isfinite(g) else m.ground.nearest_valid(xs[0]), places=9)
            else:                                                             # to the frame bottom
                self.assertEqual(ys[1], p.z_min)
            self.assertEqual(to_hex(e.get_color()), b.color)
        self.assertEqual(len([e for e in edges if to_hex(e.get_color()) == BROWN]), 0)   # Parcels: off

    def test_edge_lines_pass_behind_the_labels_under_them(self):
        """(fix 0.3.6) A longer piece stacks over a shorter one whose label overhangs its own bracket: the upper
        piece's dashed edge line stops at that label (with the halo's width around it) and goes on under it."""
        m = site_model()
        infos = list(m.other_layers)
        infos[3] = area_info(3, "Lots", GREEN, edges="full")
        pieces = [a for a in m.other_areas if a.layer_index != 3]
        pieces += [piece(3, 600.0, 650.0, "Ring pond", "Lots"), piece(3, 700.0, 900.0, "Pond B", "Lots")]
        with_rows(m, infos, m.other_points, pieces)
        fig, p = drawn(m, self.s, dpi=150)
        ax = fig.axes[0]
        r = fig.canvas.get_renderer()
        spots = {sp.text: sp for sp in S.area_layout(m, self.s, p.plot_length, z_cap=p.z_max, z_floor=p.z_min)}
        self.assertGreater(spots["Pond B"].level, spots["Ring pond"].level)  # (the case: the longer one above ...
        ring = next(t for t in label_texts(ax) if t.get_text() == "Ring pond").get_window_extent(r)
        x700 = ax.transData.transform((700.0, 0.0))[0]
        self.assertTrue(ring.x0 < x700 < ring.x1)                             # ... its end over the lower label)
        edges = [e for e in by_gid(ax, F.AREA_EDGE_GID) if to_hex(e.get_color()) == GREEN]
        at700 = sorted((e for e in edges if e.get_xdata()[0] == 700.0), key=lambda e: -max(e.get_ydata()))
        self.assertEqual(len(at700), 2)                                       # broken where it passes the label
        pond_b = next(b for b in brackets(ax) if b.a == 700.0)
        self.assertEqual((at700[0].get_ydata()[0], at700[1].get_ydata()[1]), (pond_b.y, p.z_min))   # line to bottom
        boxes = [t.get_window_extent(r) for t in label_texts(ax)]
        for e in edges:
            bb = e.get_window_extent(r)
            for lb in boxes:
                self.assertFalse(lb.x0 - 0.5 <= (bb.x0 + bb.x1) / 2.0 <= lb.x1 + 0.5
                                 and min(bb.y1, lb.y1) - max(bb.y0, lb.y0) > 0.5, (e.get_xdata()[0], lb))
            self.assertEqual((dashes(e), e.get_gid()), ((0.0, [3.0, 2.0]), F.AREA_EDGE_GID))
        self.assertEqual(len([e for e in edges if e.get_xdata()[0] != 700.0]), 3)   # the other ends: one line each

    def test_labels_never_overlap_also_with_long_names(self):
        m = site_model()
        long = [piece(2, 2100.0 + 90.0 * i, 2160.0 + 90.0 * i, f"A long wetland name number {i}", "Sites")
                for i in range(5)]
        with_rows(m, m.other_layers, m.other_points, m.other_areas + long)
        fig, _ = drawn(m, self.s, dpi=150)
        boxes = [px_box(fig, t) for t in label_texts(fig.axes[0])]
        self.assertEqual(len(boxes), 11)
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(min(a[1], b[1]) - max(a[0], b[0]) > 0 and min(a[3], b[3]) - max(a[2], b[2]) > 0,
                                 (a, b))


# ----------------------------------------------------------------------------- the elevation range
class AutoAndManual(unittest.TestCase):
    def sites(self):
        m = site_model()
        keep = [a for a in m.other_areas if a.layer_index == 2]
        return with_rows(m, m.other_layers, m.other_points, keep)

    def test_auto_leaves_room(self):
        m, s = site_model(), settings()
        for fill in ("off", "both"):
            sf = dataclasses.replace(s, fill_grid=fill)
            p = plan(m, sf)
            self.assertGreaterEqual(p.z_max, S.area_top(m, sf, p.plot_length) - 1e-9)
            self.assertFalse(any(sp.lowered for sp in S.area_layout(m, sf, p.plot_length, z_cap=p.z_max)))
            self.assertEqual(p.warnings, [])
        one = self.sites()
        one.other_areas = [a for a in one.other_areas if a.label == "Wetland A"]
        both = self.sites()
        self.assertGreater(S.area_top(both, s, 4500.0), S.area_top(one, s, 4500.0) + 0.1 * s.v_scale)

    def test_manual_with_no_room(self):
        m = self.sites()
        s = settings(z_mode="manual", z_min=50.0, z_max=MANUAL_MAX)
        p = plan(m, s)
        self.assertEqual(p.z_max, MANUAL_MAX)
        hi = S.area_top(m, s, p.plot_length)
        need = S._ceil_to(hi - S.LABEL_MARGIN_IN * s.v_scale + S.AREA_TOP_PAD_IN * s.v_scale, p.v_major)
        self.assertGreater(need, MANUAL_MAX)                                  # (the case: they do not fit)
        msg = (f"Brackets of Project site and Wetland A lowered: no room under the manual maximum of "
               f"{S.fmt_num(MANUAL_MAX)} ft. Raise it to {S.fmt_num(need)} ft or set Elevations to Auto.")
        self.assertIn(msg, p.warnings)
        self.assertEqual(len([w for w in p.warnings if w.startswith("Brackets of")]), 1)
        spots = S.area_layout(m, s, p.plot_length, z_cap=p.z_max)
        self.assertEqual([sp.lowered for sp in spots], [True, True])
        fig, _ = drawn(m, s, p=p)
        ax = fig.axes[0]
        frame_top = ax.get_window_extent(fig.canvas.get_renderer()).y1
        for t in label_texts(ax):
            self.assertLessEqual(px_box(fig, t)[3], frame_top - S.AREA_TOP_PAD_IN * fig.dpi + 1.0)   # (+1 px)
        for sp in spots:
            self.assertLessEqual(sp.top_z / s.v_scale, MANUAL_MAX / s.v_scale - S.AREA_TOP_PAD_IN + 1e-6)
        self.assertEqual(len(brackets(ax)), 2)
        # room enough at that maximum: no message
        p2 = plan(m, dataclasses.replace(s, z_max=need))
        self.assertFalse([w for w in p2.warnings if w.startswith("Brackets of")])

    def test_a_manual_minimum_over_the_ground_loses_no_bracket(self):
        """(fix 0.3.6) Where a manual minimum cuts off the ground under a piece, its bracket stands on the frame
        bottom (the layout's floor: tick bottoms AREA_CLEAR_IN over it), its stacking kept: no bracket is lost, and
        nothing more is said than what the range cuts off."""
        m = site_model()
        names = sorted(["Project site", "Wetland A", "Lot 1", "Lots", "Parcel A (continues)", "Parcel Z (continues)"])
        for z_min, z_max in ((200.0, 400.0), (300.0, 600.0)):
            s = settings(z_mode="manual", z_min=z_min, z_max=z_max)
            p = plan(m, s)
            got = []
            for i in range(len(p.pages)):
                fig, _ = drawn(m, s, index=i, p=p)
                ax = fig.axes[0]
                got += [t.get_text() for t in label_texts(ax)]
                for b in brackets(ax):
                    for t in b.ticks:
                        self.assertGreaterEqual((min(t.get_ydata()) - p.z_min) / s.v_scale, S.AREA_CLEAR_IN - 1e-9)
            self.assertEqual(sorted(set(got)), names, (z_min, z_max))
            spots = {sp.text: sp for sp in S.area_layout(m, s, p.plot_length, z_cap=p.z_max, z_floor=p.z_min)}
            self.assertFalse(any(sp.lowered for sp in spots.values()))
            self.assertAlmostEqual(spots["Lot 1"].line_z, z_min + (S.AREA_CLEAR_IN + S.AREA_TICK_IN) * s.v_scale,
                                   places=6)                                 # its ground (139 ft) cut off: on the floor
            self.assertGreater(spots["Project site"].line_z, spots["Wetland A"].top_z)        # stacking kept
            self.assertFalse([w for w in p.warnings if w.startswith("Brackets of")])
            self.assertEqual(S.area_warnings(m, s, p.plot_length, p.z_max, p.v_major, p.z_min), [])
        # a frame too short to hold them over that floor: lowered and named, with the maximum that holds them
        s = settings(z_mode="manual", z_min=250.0, z_max=270.0)
        p = plan(m, s)
        v = s.v_scale
        need = S._ceil_to(S.area_top(m, s, p.plot_length, z_floor=250.0) - S.LABEL_MARGIN_IN * v
                          + S.AREA_TOP_PAD_IN * v, p.v_major)
        msg = [w for w in p.warnings if w.startswith("Brackets of")]
        self.assertEqual(len(msg), 1)
        self.assertIn("Project site", msg[0])
        self.assertTrue(msg[0].endswith(f"Raise it to {S.fmt_num(need)} ft or set Elevations to Auto."), msg[0])


# ----------------------------------------------------------------------------- above the frame
class AboveTheFrame(unittest.TestCase):
    def model(self, rows=1, place="above"):
        m = site_model()
        parcels = [area_info(4, "Parcels", BROWN, bracket=place)]
        pieces = [a for a in m.other_areas if a.layer_index != 4]
        pieces += [piece(4, 0.0, 300.0, "Parcel A", "Parcels", open_start=True),
                   piece(4, 4300.0, LENGTH, "Parcel Z", "Parcels", open_end=True)]
        if rows == 2:                                                         # inside another: a second row
            pieces.append(piece(4, 4350.0, 4400.0, "Lot Z1", "Parcels"))
        return with_rows(m, m.other_layers[:4] + parcels, m.other_points, pieces)

    def without(self):
        m = site_model()
        return with_rows(m, m.other_layers[:4], m.other_points, [a for a in m.other_areas if a.layer_index != 4])

    def test_the_band_and_the_margins(self):
        for compact in (False, True):
            s = settings(compact_layout=compact)
            for rows in (1, 2):
                m = self.model(rows)
                p = plan(m, s)
                band = S._up(S.AREA_FRAME_GAP_IN + rows * S.AREA_ROW_IN)
                self.assertEqual(p.above_in, band)
                self.assertEqual(S.area_band_in(m, s, p.plot_length), band)
                types = S.legend_entries(m, s)
                with_band = S.margins(s, (p.z_min, p.z_max), types, 0.0, p.above_in)
                plain = S.margins(s, (p.z_min, p.z_max), types, 0.0)
                self.assertAlmostEqual(with_band["top"] - plain["top"], band, places=9, msg=(compact, rows))
                self.assertEqual({k: with_band[k] for k in ("left", "right", "bottom")},
                                 {k: plain[k] for k in ("left", "right", "bottom")})
                page = p.pages[0]
                self.assertLessEqual(page.plot_bottom + page.plot_h + with_band["top"], page.page_h + 0.006)
        self.assertEqual(S.area_band_in(self.model(1, "inside"), settings(), 4500.0), 0.0)

    def test_drawn_over_the_frame_and_the_furniture_above_it(self):
        for compact in (False, True):
            s = settings(compact_layout=compact)
            m, base = self.model(2), self.without()
            fig, p = drawn(m, s)
            fig0, p0 = drawn(base, s)
            ax, ax0 = fig.axes[0], fig0.axes[0]
            r, r0 = fig.canvas.get_renderer(), fig0.canvas.get_renderer()
            top, top0 = ax.get_window_extent(r).y1, ax0.get_window_extent(r0).y1
            # the band's brackets: over the frame top, never clipped
            above = [b for b in brackets(ax) if b.color == BROWN]
            self.assertEqual(len(above), 3)
            for b in above:
                for art in [b.line] + b.ticks + b.arrows:
                    self.assertFalse(art.get_clip_on())
                self.assertGreater(b.y, p.z_max)
            levels = sorted({round((b.y - p.z_max) * frame_inches(ax)[3], 9) for b in above})
            self.assertEqual(levels, [round(S.AREA_FRAME_GAP_IN + S.AREA_TICK_IN, 9),
                                      round(S.AREA_FRAME_GAP_IN + S.AREA_ROW_IN + S.AREA_TICK_IN, 9)])
            # the end letters, BEND labels and the title move up by the band (vs the same sheet without the row)
            def above_frame(f, a, t):
                out = {}
                for txt in list(f.texts) + [x for x in a.texts if not x.get_gid()]:
                    bb = txt.get_window_extent(f.canvas.get_renderer())
                    if txt.get_text() and bb.y0 > t - 1.0:
                        out[txt.get_text()] = bb.y0 - t
                return out
            got, ref = above_frame(fig, ax, top), above_frame(fig0, ax0, top0)
            names = ["A", "A′", "BEND"] + (["CROSS SECTION A–A′"] if not compact else [])
            for name in names:
                self.assertIn(name, ref, (compact, name))
                self.assertAlmostEqual(got[name] - ref[name], p.above_in * fig.dpi, delta=1.0, msg=(compact, name))
            # nothing above overlaps, the bracket labels included; no ink in the printer edge
            self.assertEqual(len(band_labels(fig)), 3)
            boxes = furniture(fig) + band_labels(fig)
            self.assertEqual(overlapping(boxes), [], compact)

    def test_no_ink_in_the_printer_edge(self):
        for compact in (False, True):
            for edge in (0.5, 0.3):
                s = settings(compact_layout=compact, edge_margin_in=edge)
                fig, p = drawn(self.model(2), s, dpi=100)
                rgb = np.asarray(fig.canvas.buffer_rgba())[..., :3]
                self.assertEqual(ink_in_edge(rgb, edge, 100), 0, (compact, edge))
                boxes = furniture(fig) + band_labels(fig)
                self.assertEqual(overlapping(boxes), [], (compact, edge))

    def test_edge_lines_stop_at_the_frame_bottom(self):
        """(fix 0.3.6) Rows above the frame (not clipped) with edge lines to the ground, where a manual minimum cuts
        the ground off under their ends: the lines end on the frame bottom, never under it (through the axis, the
        scale bar, the notes and the legend)."""
        m = site_model()
        infos = list(m.other_layers)
        infos[2] = area_info(2, "Sites", bracket="above", edges="ground")
        infos[4] = area_info(4, "Parcels", BROWN, bracket="above", edges="ground")
        with_rows(m, infos, m.other_points, m.other_areas)
        for z_min in (200.0, 300.0):
            s = settings(z_mode="manual", z_min=z_min, z_max=z_min + 200.0)
            fig, p = drawn(m, s)
            ax = fig.axes[0]
            r = fig.canvas.get_renderer()
            bottom = ax.get_window_extent(r).y0
            edges = [e for e in by_gid(ax, F.AREA_EDGE_GID) if to_hex(e.get_color()) in (PURPLE, BROWN)]
            self.assertEqual(len(edges), 6, z_min)                            # Sites 2 x 2 ends, Parcels 1 + 1
            cut = 0
            for e in edges:
                st = float(e.get_xdata()[0])
                self.assertFalse(e.get_clip_on())
                self.assertGreaterEqual(e.get_window_extent(r).y0, bottom - 1.0, (z_min, st))
                g = m.ground.z_at(st)
                g = g if math.isfinite(g) else m.ground.nearest_valid(st)
                self.assertEqual(min(e.get_ydata()), max(g, p.z_min), (z_min, st))
                cut += g < p.z_min
            self.assertGreater(cut, 0, z_min)                                 # (the case: some ends cut off)

    def test_the_sheet_search_sees_the_band(self):
        """A section that fits Letter landscape without the band but not with two rows: Auto goes to Letter portrait,
        Landscape to Tabloid landscape, with the same plot."""
        def section(place):                                                  # two overlapping pieces: two rows
            m = site_model()
            return with_rows(m, m.other_layers[:2] + [area_info(2, "Parcels", BROWN, bracket=place)], m.other_points,
                             [piece(2, 0.0, 300.0, "Parcel A", "Parcels", open_start=True),
                              piece(2, 100.0, 200.0, "Lot", "Parcels")])
        base, m = section("inside"), section("above")                          # (the same legend)
        s = settings(compact_layout=True, fill_grid="off", h_scale=800.0, v_scale=20.0, grid_auto=False,
                     h_major=800.0, h_minor=80.0, v_major=2.0, v_minor=1.0, z_mode="manual", z_min=0.0)
        mg = S.margins(s, (0.0, 200.0), S.legend_entries(base, s))
        room = 8.5 - mg["top"] - mg["bottom"]                                 # Letter landscape
        s.z_max = math.floor((room - 0.2) * 20.0 / 2.0) * 2.0                 # 0.1 to 0.2 in to spare
        p0 = plan(base, s)
        self.assertEqual(p0.pages[0].sheet_name, "Letter 11 × 8.5 in, landscape")
        self.assertEqual(p0.above_in, 0.0)
        p = plan(m, s)
        self.assertGreater(p.above_in, 0.4)
        self.assertEqual(p.pages[0].sheet_name, "Letter 8.5 × 11 in, portrait")
        pl = plan(m, dataclasses.replace(s, orientation="landscape"))
        self.assertEqual(pl.pages[0].sheet_name, "Tabloid 17 × 11 in, landscape")
        for q in (p, pl):
            self.assertEqual((q.pages[0].plot_w, q.pages[0].plot_h), (p0.pages[0].plot_w, p0.pages[0].plot_h))

    def test_tiled_sheets(self):
        """Every sheet of a tiled section has the band; a piece cut by a sheet's edge runs to the frame edge with no
        tick there, and every sheet showing part of a piece shows its label."""
        m = site_model()
        layers = m.other_layers[:2] + [area_info(2, "Sites", bracket="above"), area_info(3, "Lots", GREEN)]
        pieces = [piece(2, 1000.0, 2000.0, "Project site", "Sites"), piece(2, 2500.0, 3300.0, "Long site", "Sites"),
                  piece(3, 2350.0, 3100.0, "Long lot", "Lots")]
        with_rows(m, layers, m.other_points, pieces)
        s = settings(h_scale=200.0, sheet="tabloid", compact_layout=True)
        p = plan(m, s)
        self.assertGreater(len(p.pages), 1)
        self.assertGreater(p.above_in, 0.0)
        mg = S.margins(s, (p.z_min, p.z_max), S.legend_entries(m, s), 0.0, p.above_in)
        cut = 0
        for i, page in enumerate(p.pages):
            fig, _ = drawn(m, s, index=i, p=p)
            ax = fig.axes[0]
            self.assertLessEqual(page.plot_bottom + page.plot_h + mg["top"], page.page_h + 0.006)   # every sheet
            texts = [t.get_text() for t in label_texts(ax)]
            bs = brackets(ax)
            for a in pieces:
                if not (a.start < page.x_max and a.end > page.x_min):
                    continue
                color = PURPLE if a.layer_index == 2 else GREEN
                b = next(br for br in bs if br.color == color and br.a == max(a.start, page.x_min))
                self.assertEqual(b.b, min(a.end, page.x_max))                 # to the frame edge where it is cut
                ticks = sorted(float(t.get_xdata()[0]) for t in b.ticks)
                self.assertEqual(ticks, [x for x in (a.start, a.end) if page.x_min <= x <= page.x_max], (i, a.label))
                self.assertIn(a.label, texts, (i, a.label))                   # its label on every sheet showing it
                cut += a.start < page.x_min or a.end > page.x_max
        self.assertGreaterEqual(cut, 2)


# ----------------------------------------------------------------------------- legend, preview, the old look
class LegendPreviewAndOldLook(unittest.TestCase):
    def test_legend_entries_and_swatches(self):
        m = site_model(lots_style="dash")
        m.other_layers.append(area_info(5, "Empty", "#123456"))               # no piece: not listed
        s = settings()
        entries = [e for e in S.legend_entries(m, s) if e.kind in ("point", "area")]
        self.assertEqual(entries, [S.LegendEntry("Seeps", "point", 0), S.LegendEntry("Streams", "point", 1),
                                   S.LegendEntry("Sites", "area", 2), S.LegendEntry("Lots", "area", 3),
                                   S.LegendEntry("Parcels", "area", 4)])
        for compact in (False, True):
            fig, _ = drawn(m, settings(compact_layout=compact))
            sw = [a for a in fig.artists if a.get_gid() == F.LEGEND_AREA_GID]
            # a solid row: one polyline (tick, line, tick); a dashed one as on the sheet (fix 0.3.6): the line dashed,
            # its two ticks one solid line from half the line's width above it (they cover the corners)
            self.assertEqual([to_hex(a.get_color()) for a in sw], [PURPLE, GREEN, GREEN, BROWN])
            for a in sw:
                self.assertIsInstance(a, Line2D)
                self.assertEqual(a.get_linewidth(), S.AREA_LW)
            for a in (sw[0], sw[3]):
                self.assertEqual(len(a.get_xdata()), 4)
                xs, ys = a.get_xdata(), a.get_ydata()
                self.assertAlmostEqual(xs[2] - xs[0], S.SWATCH_IN, places=9)
                self.assertAlmostEqual(ys[1] - ys[0], 0.05, places=9)
                self.assertEqual(a.get_linestyle(), "-")
            line, ticks = sw[1], sw[2]
            self.assertEqual(dashes(line), (0.0, [4.0, 2.0]))
            lx, ly = line.get_xdata(), line.get_ydata()
            self.assertEqual(len(lx), 2)
            self.assertAlmostEqual(lx[1] - lx[0], S.SWATCH_IN, places=9)
            self.assertEqual(ticks.get_linestyle(), "-")
            tx, ty = np.asarray(ticks.get_xdata(), float), np.asarray(ticks.get_ydata(), float)
            self.assertEqual(len(tx), 5)
            self.assertTrue(math.isnan(tx[2]) and math.isnan(ty[2]))
            self.assertEqual((tx[0], tx[1], tx[3], tx[4]), (lx[0], lx[0], lx[1], lx[1]))
            for top in (ty[1], ty[3]):
                self.assertAlmostEqual(top - ly[0], S.AREA_LW / 144.0, places=9)
            for foot in (ty[0], ty[4]):
                self.assertAlmostEqual(ly[0] - foot, 0.05, places=9)
        # more entries, more legend: the margins grow as for any entry
        sc = settings(compact_layout=True)
        few = S.legend_entries(with_rows(site_model(), site_model().other_layers[:2], site_model().other_points), sc)
        many = S.legend_entries(m, sc) + [S.LegendEntry(f"Area {i}", "area", 2) for i in range(12)]
        self.assertGreater(S.margins(sc, (0.0, 300.0), many)["bottom"], S.margins(sc, (0.0, 300.0), few)["bottom"])

    def test_preview(self):
        m = site_model(parcels="above")
        s = settings()
        p = plan(m, s)
        self.assertGreater(p.above_in, 0.0)
        fig = Figure(figsize=(10.0, 4.0), dpi=100)
        FigureCanvasAgg(fig)
        placed = F.draw_preview(fig, m, s, p)
        ax = fig.axes[0]
        bs = brackets(ax)
        self.assertEqual(len(bs), 6)
        self.assertTrue([b for b in bs if b.y > p.z_max] and [b for b in bs if b.y < p.z_max])   # above and inside
        top_in = ax.get_position().y1 * 4.0
        self.assertLessEqual(top_in, 4.0 - 0.55 - p.above_in + 1e-9)           # mt grew by the band
        kinds = {m.other_points[pp.index].kind for pp in placed}
        self.assertEqual(kinds, {"crossing", "point"})
        self.assertEqual(len(placed), 3)

    def test_the_preview_lays_the_brackets_out_at_its_own_scale(self):
        """(fix 0.3.6) The preview's labels are relatively larger than the sheet's (its text never under 0.85 of the
        sheet's while the drawing shrinks more): it stacks the brackets over its own exploration and point labels, so
        every piece keeps its label and none covers another label or an end letter. (A preview too small to hold
        them under its frame top lowers them as a manual range does, without a word: then only every label is kept,
        none over another bracket label.)"""
        names = sorted(["Project site", "Wetland A", "Lot 1", "Lots", "Parcel A (continues)", "Parcel Z (continues)"])
        s = settings()
        for parcels in ("inside", "above"):
            m = site_model(parcels=parcels)
            p = plan(m, s)
            for size in ((14.0, 6.0), (12.0, 5.5), (8.0, 3.5)):
                room = size != (8.0, 3.5)                                     # (8 x 3.5: lowered)
                fig = Figure(figsize=size, dpi=100)
                FigureCanvasAgg(fig)
                F.draw_preview(fig, m, s, p)
                fig.canvas.draw()
                ax = fig.axes[0]
                r = fig.canvas.get_renderer()
                mine = label_texts(ax)
                self.assertEqual(sorted(t.get_text() for t in mine), names, (parcels, size))
                others = [t for t in ax.texts if t.get_text().strip()
                          and t.get_gid() not in (F.AREA_LABEL_GID, F.AREA_LABEL_HALO_GID)]
                self.assertTrue(others)
                boxes = [(t.get_text(), t.get_window_extent(r)) for t in mine]

                def overlap(a, b, by):
                    return min(a.x1, b.x1) - max(a.x0, b.x0) > by and min(a.y1, b.y1) - max(a.y0, b.y0) > by
                for i, (name, a) in enumerate(boxes):
                    for o in others if room else []:
                        self.assertFalse(overlap(a, o.get_window_extent(r), 0.5),
                                         f"{name!r} overlaps {o.get_text()!r} {(parcels, size)}")
                    for other, b in boxes[i + 1:]:
                        self.assertFalse(overlap(a, b, 0.0), f"{name!r} overlaps {other!r} {(parcels, size)}")

    def test_old_sheets_are_unchanged(self):
        m = hits_model(length=LENGTH)
        with_rows(m, [point_info(0)], [seep("S-1", 1700.0, m.ground, 0)])
        for compact in (False, True):
            s = settings(compact_layout=compact)
            p = plan(m, s)
            self.assertEqual(S.area_layout(m, s, p.plot_length), [])
            self.assertEqual(p.above_in, 0.0)
            self.assertEqual(S.area_band_in(m, s, p.plot_length), 0.0)
            self.assertEqual(S.area_top(m, s, p.plot_length), -math.inf)
            self.assertEqual(S.area_warnings(m, s, p.plot_length, p.z_max, p.v_major), [])
            types = S.legend_entries(m, s)
            self.assertEqual(S.margins(s, (p.z_min, p.z_max), types, 0.0, 0.0), S.margins(s, (p.z_min, p.z_max), types))
            fig, _ = drawn(m, s)
            self.assertEqual([a for a in fig.axes[0].lines if a.get_gid() in (F.AREA_GID, F.AREA_EDGE_GID)], [])


if __name__ == "__main__":
    unittest.main()
