"""Older projects look exactly as before: golden files made once from the 0.3.2 tree (DESIGN.md decision 9).

tests/data/compat_032/ holds, per case, the 0.3.2 settings JSON (layer ids replaced by placeholders) and what 0.3.2
made from it: every Hit, the Plan, a few model fields, every exported sheet (PNG at 100 dpi) and, for two cases, the
preview. Each case is loaded three ways (Settings.from_json, settings_store.load, and the panel: restore_from_project
then settings()) and each must give exactly the golden outputs: hits matched by position, only the golden's keys
compared (fields added later are ignored), floats within 1e-9, PNGs pixel for pixel. Since 0.3.5 a hit's direction
is the direction of projection (from the exploration onto the line), the reverse of the one 0.3.2 wrote (from the
line to the exploration): 0.3.2's directions are compared reversed (_hits_golden).

The goldens are made by this module, in the test runner (same Python, matplotlib and fonts as every check), with
the environment variable XSECTIONS_MAKE_GOLDEN=1: it writes the files and skips. That was done ONCE, on the untouched
0.3.2 tree. Never make them again without the user's approval: a mismatch is a bug in the change, not in the golden
(making them refuses to run while the folder holds files). The inputs are frozen with the outputs: the layers come
from the 0.3.2 builders of tests.fixtures and the literal copies below, the settings from the golden JSON.
0.3.4: the bytype case was made again once, with the user's approval (REMADE).
0.3.5: the manual case (it labels the directions) was made again once, with the user's approval (REMADE): its sheets
and its hits' direction values (NEW_DIRECTIONS).
"""
import dataclasses
import json
import math
import os
import re
import tempfile
import unittest

from tests.fixtures import (CRS, STANDARD_LAYOUT, default_settings, load_project, plane_z, point_at,
                            start_app)

APP = start_app()

import matplotlib  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer  # noqa: E402
from qgis.PyQt.QtCore import QDate, QMetaType  # noqa: E402

from tests.measure import load_png  # noqa: E402
from tests.test_ui import make_iface  # noqa: E402
from xsections.core import model as core_model  # noqa: E402
from xsections.core.build import build_section  # noqa: E402
from xsections.core.model import Settings  # noqa: E402
from xsections.render import figure as F  # noqa: E402
from xsections.render import scales as S  # noqa: E402
from xsections.render.export import export  # noqa: E402
from xsections.ui import settings_store  # noqa: E402
from xsections.ui.dock import XSectionsDock  # noqa: E402

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "compat_032")
MAKE = os.environ.get("XSECTIONS_MAKE_GOLDEN", "") == "1"
# A case made again, only with the user's approval and only through remake_case (XSECTIONS_REMAKE_GOLDEN=<case>): its
# plan and sheets are written again; its settings, hits and model goldens never are.
REMAKE = os.environ.get("XSECTIONS_REMAKE_GOLDEN", "")
REMADE = {"bytype": "0.3.4: Data lines By type became Color from the layer style (approved by the user, 2026-10-08)",
          "manual": "0.3.5: the label directions became the direction of projection onto the line (asked for by "
                    "the user, 2026-10-09)"}
# 0.3.5: Hit.direction is the direction of projection, from the exploration onto the line; 0.3.2 wrote the direction
# from the line to the exploration, its reverse. A 0.3.2 hits golden is read with each direction reversed; the cases in
# NEW_DIRECTIONS were made again with 0.3.5's directions (only the direction values of their hits golden rewritten).
OPPOSITE = {"N": "S", "NE": "SW", "E": "W", "SE": "NW", "S": "N", "SW": "NE", "W": "E", "NW": "SE", "": ""}
NEW_DIRECTIONS = ("manual",)
CASES = ("basic", "wells", "bytype", "manual", "ground")
PREVIEW_CASES = ("basic", "wells")
PATHS = ("json", "store", "panel")
TOL = 1e-9
MODEL_KEYS = ("warnings", "beyond_ends", "near_count", "has_explorations", "points_name")
PLACEHOLDER = re.compile(r'"\{([a-z]+)\}"')


# ----------------------------------------------------------------------------- the frozen inputs
# Literal copies of tests/test_wells_surfaces.py (0.3.2): _wells_layer, _wl_table and the keys of
# ScreensInTheModel.settings(). Frozen with the goldens: never edit them.
def _wells_layer():
    lyr = QgsVectorLayer(f"Point?crs={CRS}", "wells", "memory")
    lyr.dataProvider().addAttributes([
        QgsField("ExploName", QMetaType.Type.QString), QgsField("ExploType", QMetaType.Type.QString),
        QgsField("ExploDepth", QMetaType.Type.Double), QgsField("ExploElev", QMetaType.Type.Double),
        QgsField("ScrTop", QMetaType.Type.Double), QgsField("ScrBot", QMetaType.Type.Double),
        QgsField("WL_Elev", QMetaType.Type.Double), QgsField("WL_Date", QMetaType.Type.QDate),
        QgsField("ATD_Elev", QMetaType.Type.Double), QgsField("DTW", QMetaType.Type.Double)])
    lyr.updateFields()
    rows = [  # name, station, offset, depth, scr top, scr bot, WL (relative to LIDAR), WL date, ATD (relative)
        ("W-1", 900.0, 20.0, 40.0, 25.0, 35.0, -8.0, QDate(2025, 6, 12), -5.0),
        ("W-2", 2000.0, -30.0, 30.0, 10.0, None, None, None, None),
        ("B-9", 3000.0, 15.0, 25.0, None, None, None, None, 0.0),
        ("W-3", 3500.0, -10.0, 30.0, None, None, "abs20", None, None),
    ]
    feats = []
    for name, st, off, depth, sa, sb, wl, date, atd in rows:
        x, y = point_at(st, off)
        z = plane_z(x, y)
        f = QgsFeature(lyr.fields())
        wl_v = 20.0 if wl == "abs20" else (None if wl is None else round(z + wl, 2))
        atd_v = None if atd is None else (0.0 if atd == 0.0 else round(z + atd, 2))
        f.setAttributes([name, "Well", depth, None, sa, sb, wl_v, date, atd_v, 8.0 if name == "W-1" else None])
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    lyr.updateExtents()
    return lyr


def _wl_table():
    t = QgsVectorLayer("None", "water_levels", "memory")
    t.dataProvider().addAttributes([QgsField("Name", QMetaType.Type.QString), QgsField("Elev", QMetaType.Type.Double),
                                    QgsField("Date", QMetaType.Type.QString), QgsField("Kind", QMetaType.Type.QString)])
    t.updateFields()
    feats = []
    x2, y2 = point_at(2000.0, -30.0)
    x9, y9 = point_at(3000.0, 15.0)
    for name, elev, date, kind in [("W-2", plane_z(x2, y2) - 6.0, "1/5/2024", "ATD"),
                                   ("W-2", plane_z(x2, y2) - 18.0, "1/6/2024", "ATD"),
                                   (" w-1 ", 512.0, "3/1/2025", "Static"),
                                   ("B-9", plane_z(x9, y9) - 4.0, "", "atd drilling"),
                                   ("Nowhere", 500.0, "", "ATD")]:
        f = QgsFeature(t.fields())
        f.setAttributes([name, elev, date, kind])
        feats.append(f)
    t.dataProvider().addFeatures(feats)
    return t


def _wells_keys(wells, table):
    """ScreensInTheModel.settings() of 0.3.2 (its base keys)."""
    return dict(points_layer_id=wells.id(), type_field="", screen_top_field="ScrTop",
                screen_bottom_field="ScrBot", wl_field="WL_Elev", wl_date_field="WL_Date", atd_field="ATD_Elev",
                wl_table_id=table.id(), wl_table_name_field="Name", wl_table_elev_field="Elev",
                wl_table_date_field="Date", wl_table_kind_field="Kind")


def _type_renderer():
    """(0.3.4) The explorations' style, frozen with the remade bytype goldens: categorized by ExploType, each type in
    its colour (a memory layer's own default symbol has a random colour). Only rows drawn in Color read it."""
    from qgis.core import QgsCategorizedSymbolRenderer, QgsMarkerSymbol, QgsRendererCategory
    cats = [("Boring", "#df9560"), ("Monitoring Well", "#3fcaa2"), ("Test Pit", "#80a7ea"), ("CPT", "#cec063")]
    return QgsCategorizedSymbolRenderer("ExploType", [
        QgsRendererCategory(value, QgsMarkerSymbol.createSimple({"color": color, "outline_color": "#232323"}), value,
                            True) for value, color in cats])


def _project():
    """One project for every case: DEM, explorations (with BotElev, drawn with _type_renderer), the section line,
    the wells and their water-level table. Returns {placeholder name: layer}, plus "prj"."""
    prj, dem, pts, lines = load_project(bot_elev=True)
    pts.setRenderer(_type_renderer())
    wells, table = _wells_layer(), _wl_table()
    prj.addMapLayers([wells, table])
    return dict(prj=prj, dem=dem, pts=pts, lines=lines, wells=wells, table=table)


def _layers(L):
    return {k: v for k, v in L.items() if k != "prj"}


# Used only to MAKE the goldens (the checks read the settings from the golden JSON).
def _case_settings(case, L):
    prj, dem, pts, lines = L["prj"], L["dem"], L["pts"], L["lines"]

    def basic(**over):
        kw = dict(bottom_elev_field="BotElev", types=["Boring", "Monitoring Well", "CPT"], h_scale=200.0,
                  v_scale=20.0, **STANDARD_LAYOUT)
        kw.update(over)
        return default_settings(prj, dem, pts, lines, **kw)

    if case == "basic":
        return basic()
    if case == "wells":
        kw = _wells_keys(L["wells"], L["table"])
        kw.update(wl_label="elev_date", sheet="custom", h_scale=500.0, v_scale=20.0)
        return default_settings(prj, dem, L["wells"], lines, **kw)
    if case == "bytype":     # the default sheet style: compact layout, grid filled below
        return basic(data_color="type", compact_layout=True, fill_grid="below")
    if case == "manual":     # z_min above the bottoms of B-2 (497.4) and CPT-1 (~493): checked when made
        return basic(z_mode="manual", z_min=500.0, z_max=600.0, label_vertical=False, label_offset=True,
                     td_label=False)
    if case == "ground":     # no points layer (the other per-layer keys left as basic has them)
        return basic(points_layer_id="")
    raise ValueError(case)


# ----------------------------------------------------------------------------- settings text and the three paths
def _with_placeholders(text, L):
    for name, layer in _layers(L).items():
        text = text.replace(json.dumps(layer.id()), json.dumps("{" + name + "}"))
    for name, layer in _layers(L).items():
        assert layer.id() not in text, (name, text)
    return text


def _with_ids(text, L):
    layers = _layers(L)

    def sub(m):
        if m.group(1) not in layers:
            raise AssertionError(f"unknown placeholder {m.group(0)}")
        return json.dumps(layers[m.group(1)].id())
    return PLACEHOLDER.sub(sub, text)


def _golden(name):
    return os.path.join(GOLDEN, name)


def _read_text(case, L):
    with open(_golden(f"{case}.json"), encoding="utf-8") as fh:
        return _with_ids(fh.read().strip(), L)


def _load(path, text, prj):
    """The settings as `path` loads `text`: from_json, the project store, or the panel."""
    if path == "json":
        return Settings.from_json(text)
    prj.writeEntry(settings_store.SCOPE, settings_store.KEY, text)
    try:
        if path == "store":
            s = settings_store.load(prj)
            assert s is not None
            return s
        d = XSectionsDock(make_iface(), None)
        try:
            d.restore_from_project()
            return d.settings()
        finally:
            d.cleanup()
            d.deleteLater()
            APP.processEvents()
    finally:
        settings_store.clear(prj)


# ----------------------------------------------------------------------------- outputs
def _plain(obj):
    """JSON-ready plain data (dataclasses as dicts), round-tripped through json so goldens and fresh outputs
    compare like for like."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        obj = dataclasses.asdict(obj)
    return json.loads(json.dumps(obj))


def _outputs(s, prj, folder, prefix, preview):
    """Build, plan and export `s`: {hits, plan, model, sheets: [png paths], preview: png path or None}."""
    model = build_section(s, prj)
    plan = S.plan(model, s)
    sheets = export(model, s, plan, os.path.join(folder, f"{prefix}.png"), "png", dpi=100)
    pv = None
    if preview:
        pv = os.path.join(folder, f"{prefix}_preview.png")
        with matplotlib.rc_context(F.RC):
            fig = Figure(figsize=(9, 3.5), dpi=100)
            F.draw_preview(fig, model, s, plan)
            fig.savefig(pv, format="png", dpi=100, facecolor="white")
    return dict(hits=_plain([dataclasses.asdict(h) for h in model.hits]), plan=_plain(plan),
                model=_plain({k: getattr(model, k) for k in MODEL_KEYS}), sheets=sheets, preview=pv)


def _write_json(name, obj):
    with open(_golden(name), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=1)
        fh.write("\n")


def _read_json(name):
    with open(_golden(name), encoding="utf-8") as fh:
        return json.load(fh)


def _reversed(hits):
    """0.3.2's hits with each direction reversed (0.3.5's direction of projection)."""
    return [dict(h, direction=OPPOSITE[h["direction"]]) if "direction" in h else h for h in hits]


def _hits_golden(prefix):
    """The hits golden of `prefix` as 0.3.5 must give it: 0.3.2's directions reversed, or as written for a case made
    again with 0.3.5's directions (NEW_DIRECTIONS)."""
    hits = _read_json(f"{prefix}_hits.json")
    case = prefix[:-len("_panel")] if prefix.endswith("_panel") else prefix
    return hits if case in NEW_DIRECTIONS else _reversed(hits)


def _sheet_key(name):
    m = re.search(r"_sheet(\d+)\.png$", name)
    return int(m.group(1)) if m else 0


def _golden_sheets(prefix):
    pat = re.compile(re.escape(prefix) + r"(_sheet\d+)?\.png$")
    return sorted((n for n in os.listdir(GOLDEN) if pat.fullmatch(n)), key=_sheet_key)


# ----------------------------------------------------------------------------- comparison
def _diff(golden, new, where="", out=None):
    """Differences between a golden value and a fresh one (only the golden's keys; floats within TOL)."""
    out = [] if out is None else out
    if isinstance(golden, dict):
        if not isinstance(new, dict):
            out.append(f"{where}: {new!r} is not a dict")
            return out
        for k, g in golden.items():
            if k not in new:
                out.append(f"{where}.{k}: missing")
            else:
                _diff(g, new[k], f"{where}.{k}", out)
    elif isinstance(golden, list):
        if not isinstance(new, list):
            out.append(f"{where}: {new!r} is not a list")
        elif len(golden) != len(new):
            out.append(f"{where}: {len(new)} items, golden {len(golden)}: {new!r} vs {golden!r}")
        else:
            for i, (g, n) in enumerate(zip(golden, new)):
                _diff(g, n, f"{where}[{i}]", out)
    elif isinstance(golden, bool) or golden is None or isinstance(golden, str):
        if type(new) is not type(golden) or new != golden:
            out.append(f"{where}: {new!r}, golden {golden!r}")
    elif isinstance(golden, (int, float)):
        if isinstance(new, bool) or not isinstance(new, (int, float)):
            out.append(f"{where}: {new!r}, golden {golden!r}")
        elif math.isnan(golden) or math.isnan(new):
            if not (math.isnan(golden) and math.isnan(new)):
                out.append(f"{where}: {new!r}, golden {golden!r}")
        elif math.isinf(golden) or math.isinf(new):
            if golden != new:
                out.append(f"{where}: {new!r}, golden {golden!r}")
        elif abs(new - golden) > TOL:
            out.append(f"{where}: {new!r}, golden {golden!r} (off by {new - golden:.3g})")
    else:
        out.append(f"{where}: golden of unexpected kind {golden!r}")
    return out


def _png_diff(golden_path, new_path):
    """'' when the decoded RGB images are identical, else what differs."""
    a, b = load_png(golden_path)[0], load_png(new_path)[0]
    name = os.path.basename(golden_path)
    if a.shape != b.shape:
        return f"{name}: {b.shape[1]} x {b.shape[0]} px, golden {a.shape[1]} x {a.shape[0]} px"
    bad = np.any(a != b, axis=2)
    if not bad.any():
        return ""
    rows, cols = np.nonzero(bad)
    return (f"{name}: {int(bad.sum())} pixels differ, within x {cols.min()}-{cols.max()}, "
            f"y {rows.min()}-{rows.max()} (max channel difference "
            f"{int(np.abs(a.astype(int) - b.astype(int)).max())})")


def _compare(prefix, out, preview):
    """Every difference between fresh outputs and the goldens of `prefix`."""
    diffs = []
    _diff(_hits_golden(prefix), out["hits"], "hits", diffs)
    _diff(_read_json(f"{prefix}_plan.json"), out["plan"], "plan", diffs)
    _diff(_read_json(f"{prefix}_model.json"), out["model"], "model", diffs)
    want = _golden_sheets(prefix)
    got = [os.path.basename(p) for p in out["sheets"]]
    if got != want:
        diffs.append(f"sheets: {got}, golden {want}")
    else:
        for name, p in zip(want, out["sheets"]):
            d = _png_diff(_golden(name), p)
            if d:
                diffs.append(d)
    if preview:
        d = _png_diff(_golden(f"{prefix}_preview.png"), out["preview"])
        if d:
            diffs.append(d)
    return diffs


# ----------------------------------------------------------------------------- making the goldens (once)
def make_goldens():
    """Write tests/data/compat_032/ from the running tree (must be the untouched 0.3.2 tree). Returns notes."""
    if core_model.SETTINGS_VERSION != 5 or "point_layers" in {f.name for f in dataclasses.fields(Settings)}:
        raise AssertionError("The goldens are made from the 0.3.2 tree only (settings version 5).")
    if os.path.isdir(GOLDEN) and os.listdir(GOLDEN):
        raise AssertionError(f"{GOLDEN} already holds golden files. They are never made again without the "
                             "user's approval; delete the folder first only with it.")
    os.makedirs(GOLDEN, exist_ok=True)
    L = _project()
    notes = []
    try:
        for case in CASES:
            s = _case_settings(case, L)
            with open(_golden(f"{case}.json"), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(_with_placeholders(s.to_json(), L) + "\n")
            text = _read_text(case, L)
            preview = case in PREVIEW_CASES
            out = _outputs(_load("json", text, L["prj"]), L["prj"], GOLDEN, case, preview)
            if case == "manual":
                low = {h["label"]: h["bottom"] for h in out["hits"]}
                assert s.z_min > max(low["B-2"], low["CPT-1"]), low
            _write_json(f"{case}_hits.json", out["hits"])
            _write_json(f"{case}_plan.json", out["plan"])
            _write_json(f"{case}_model.json", out["model"])
            for path in PATHS[1:]:
                folder = tempfile.mkdtemp(prefix=f"xsec_compat_{case}_{path}_")
                other = _outputs(_load(path, text, L["prj"]), L["prj"], folder, case, preview)
                diffs = _compare(case, other, preview)
                if not diffs:
                    continue
                if path != "panel":
                    raise AssertionError(f"{case} through {path} differs from from_json: " + "; ".join(diffs))
                prefix = f"{case}_panel"           # the panel's own goldens (0.3.2 gives it other output)
                out = _outputs(_load(path, text, L["prj"]), L["prj"], GOLDEN, prefix, preview)
                _write_json(f"{prefix}_hits.json", out["hits"])
                _write_json(f"{prefix}_plan.json", out["plan"])
                _write_json(f"{prefix}_model.json", out["model"])
                notes.append(f"{case}: the panel differs from from_json ({'; '.join(diffs[:3])}): "
                             f"{prefix}_* goldens written")
    finally:
        QgsProject.instance().clear()
    return notes


# ----------------------------------------------------------------------------- making one case again (approved)
def remake_case(case):
    """Make the plan and the sheets of `case` again from the running tree, only for a case in REMADE (the user's
    approval) and settings version 7 or later. Its settings (case.json) and model goldens are never written, nor its
    hits golden, except (a case in NEW_DIRECTIONS, 0.3.5) the direction values in it: every other value must still
    match (a hits golden written from 0.3.4's Hit would hold a memory layer's random id), each direction 0.3.2's
    reversed (or already 0.3.5's). The plan is written only when it differs. The store and the panel paths must give
    exactly what the json path gives (only _outputs results are compared), and no _panel_ golden is written. Returns
    a note: the direction changes, the plan differences and the sheets written."""
    if case not in REMADE:
        raise AssertionError(f"{case!r} may not be made again: only {sorted(REMADE)} (with the user's approval)")
    if core_model.SETTINGS_VERSION < 7:
        raise AssertionError("The bytype case is made again from settings version 7 (0.3.4) on only.")
    L = _project()
    try:
        prj = L["prj"]
        text = _read_text(case, L)
        preview = case in PREVIEW_CASES
        tmp = tempfile.mkdtemp(prefix=f"xsec_remake_{case}_")
        out = _outputs(_load("json", text, prj), prj, tmp, case, preview)
        golden_hits = _read_json(f"{case}_hits.json")
        want_hits = _hits_golden(case)
        if case in NEW_DIRECTIONS and _diff(golden_hits, out["hits"]):
            want_hits = _reversed(golden_hits)                  # 0.3.2's directions, not made again yet
        fixed = []
        _diff(want_hits, out["hits"], "hits", fixed)
        _diff(_read_json(f"{case}_model.json"), out["model"], "model", fixed)
        if fixed:
            raise AssertionError(f"{case}: the hits (but 0.3.5's directions) and the model may not change: "
                                 + "; ".join(fixed[:10]))
        for path in PATHS[1:]:
            folder = tempfile.mkdtemp(prefix=f"xsec_remake_{case}_{path}_")
            other = _outputs(_load(path, text, prj), prj, folder, case, preview)
            diffs = []
            _diff(want_hits, other["hits"], "hits", diffs)
            _diff(_read_json(f"{case}_model.json"), other["model"], "model", diffs)
            _diff(out["plan"], other["plan"], "plan", diffs)
            names = [os.path.basename(x) for x in out["sheets"]]
            if [os.path.basename(x) for x in other["sheets"]] != names:
                diffs.append(f"sheets: {[os.path.basename(x) for x in other['sheets']]}, json path {names}")
            else:
                diffs += [d for d in (_png_diff(a, b) for a, b in zip(out["sheets"], other["sheets"])) if d]
            if preview:
                d = _png_diff(out["preview"], other["preview"])
                if d:
                    diffs.append(d)
            if diffs:
                raise AssertionError(f"{case} through {path} differs from the json path: " + "; ".join(diffs[:10]))
        plan_diffs = _diff(_read_json(f"{case}_plan.json"), out["plan"], "plan")
        old = _golden_sheets(case)
        for name in old:
            os.remove(_golden(name))
        written = _outputs(_load("json", text, prj), prj, GOLDEN, case, preview)
        again = _diff(out["plan"], written["plan"], "plan")
        again += [d for d in (_png_diff(a, b) for a, b in zip(out["sheets"], written["sheets"])) if d]
        if again or len(written["sheets"]) != len(out["sheets"]):
            raise AssertionError(f"{case}: a second build differs from the first: " + "; ".join(again[:10]))
        if plan_diffs:
            _write_json(f"{case}_plan.json", written["plan"])      # (a preview case's preview: written above)
        turned = []
        if case in NEW_DIRECTIONS:              # only the direction values of the golden's own hits, in place
            new_hits = [dict(g, direction=h["direction"]) for g, h in zip(golden_hits, out["hits"])]
            turned = [f"{g['label']} {g['direction']} -> {n['direction']}"
                      for g, n in zip(golden_hits, new_hits) if g != n]
            if turned:
                _write_json(f"{case}_hits.json", new_hits)
        new = [os.path.basename(x) for x in written["sheets"]]
        return (f"{case} made again ({REMADE[case]}): directions {turned if turned else 'unchanged'}; plan "
                f"differences {plan_diffs if plan_diffs else 'none (not written)'}; sheets removed {old}, written {new}")
    finally:
        QgsProject.instance().clear()


# ----------------------------------------------------------------------------- the checks
class Compat032(unittest.TestCase):
    """Each case, loaded three ways, gives exactly what 0.3.2 gave (bytype: what 0.3.4 gives, REMADE)."""

    @classmethod
    def setUpClass(cls):
        if MAKE:
            notes = make_goldens()
            raise unittest.SkipTest("golden files written to tests/data/compat_032"
                                    + (": " + " | ".join(notes) if notes else " (the panel matches from_json)"))
        if REMAKE:
            raise unittest.SkipTest(remake_case(REMAKE))
        if not (os.path.isdir(GOLDEN) and os.path.isfile(_golden("basic_hits.json"))):
            raise AssertionError(f"golden files missing in {GOLDEN}")
        cls.L = _project()
        cls.tmp = tempfile.mkdtemp(prefix="xsec_compat_")

    @classmethod
    def tearDownClass(cls):
        QgsProject.instance().clear()

    def check(self, case, path):
        prj = self.L["prj"]
        text = _read_text(case, self.L)
        self.assertIsNone(PLACEHOLDER.search(text))
        s = _load(path, text, prj)
        prefix = case
        if path == "panel" and os.path.isfile(_golden(f"{case}_panel_hits.json")):
            prefix = f"{case}_panel"
        preview = case in PREVIEW_CASES
        folder = tempfile.mkdtemp(prefix=f"{case}_{path}_", dir=self.tmp)
        diffs = _compare(prefix, _outputs(s, prj, folder, prefix, preview), preview)
        if diffs:
            self.fail(f"{case} through {path} differs from 0.3.2 ({len(diffs)} differences):\n"
                      + "\n".join(diffs[:25]))

    def test_golden_files_complete(self):
        names = set(os.listdir(GOLDEN))
        for case in CASES:
            for suffix in (".json", "_hits.json", "_plan.json", "_model.json"):
                self.assertIn(case + suffix, names)
            self.assertTrue(_golden_sheets(case), case)
            self.assertEqual(case in PREVIEW_CASES, f"{case}_preview.png" in names, case)
            with open(_golden(f"{case}.json"), encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["version"], 5, case)                 # stored by 0.3.2
        self.assertEqual(_read_json("ground_hits.json"), [])

    def test_bytype_takes_the_layer_style(self):
        """(0.3.4) The remade bytype sheets draw the Borings and the Monitoring Wells in their colours of the layer's
        style (_type_renderer); basic's (a Black row) have none of them."""
        def count(prefix, color):
            want = np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)])
            n = 0
            for name in _golden_sheets(prefix):
                rgb = load_png(_golden(name))[0].astype(int)
                n += int(np.all(np.abs(rgb - want) <= 3, axis=2).sum())
            return n
        for color in ("#df9560", "#3fcaa2"):
            self.assertGreaterEqual(count("bytype", color), 20, color)
            self.assertEqual(count("basic", color), 0, color)

    def test_manual_directions_are_projections(self):
        """(0.3.5) The remade manual hits golden holds the direction of projection: the reverse of basic's 0.3.2
        directions for the same explorations (B-1 lies north of the eastward line: 0.3.2 wrote N, 0.3.5 S), every
        other value as basic's."""
        basic, manual = _read_json("basic_hits.json"), _read_json("manual_hits.json")
        self.assertEqual([h["label"] for h in manual], [h["label"] for h in basic])
        self.assertEqual(manual, _reversed(basic))
        self.assertEqual(next(h["direction"] for h in manual if h["label"] == "B-1"), "S")


def _add_checks():
    for case in CASES:
        for i, path in enumerate(PATHS, 1):
            def test(self, case=case, path=path):
                self.check(case, path)
            test.__name__ = f"test_{case}_{i}_{path}"
            test.__doc__ = f"{case}: loaded through {path}, the 0.3.2 output"
            setattr(Compat032, test.__name__, test)


_add_checks()


if __name__ == "__main__":
    unittest.main()
