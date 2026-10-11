"""What a build's warnings become in the panel (0.3.6, DESIGN.md decision 27, D14): a real problem of a row (something
left off the sheet or changed on it) is ONE short amber line in that row, a count on its check badge and a block of
its check card, whatever Verbose is; a guess is the row's own business (its "check" badge, ui.point_rows); a note (the
readouts' facts, "Left out past the ends ...") shows only with Verbose; what no row owns stays in the status line.

Pure: no widgets are made and no layer is read here (the dock reads a water-level table's bad values into
RowState.table_bad). Each *_problems function returns, per row in panel order, its problems (widgets.Problem, in the
order of the table in the spec) and the set of model.warnings strings they cover; status_warnings leaves those out.
With `model` None (no build, or a failed one) only the problems the rows know by themselves come back (a missing
layer).
"""
from __future__ import annotations

import re
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

from ..core.model import NO_POINTS
from .widgets import CARD_ITEMS, CardInfo, Problem

NOTE_PREFIXES = ("Left out past the ends", "No DEM data along")      # notes (readouts) or a row's problem
SCREEN_FLAG = re.compile(r"screen|water|\bwl\b|\batd\b", re.IGNORECASE)   # a flag about screens or water levels
# core texts that name 0.3.5's panel (the core is not edited by the panel build): shown with the place of today
OLD_PLACES = (("Surfaces > More: units and datum", "Surfaces › Units & datum"),
              ("(see Plotted explorations)", "(see Explorations › Plotted)"))
UNITS_WORDS = "does not state its"      # a units assumption: the status line, never a row (choice 14)

# a water-level table's not-number warning (core.explorations._not_numbers_warning)
_WL_BAD = re.compile(r"^(?P<table>.*): (?P<n>[0-9][0-9,]*) water levels? in (?P<field>.*) "
                     r"(?:are not numbers|is not a number) \(left out\)\.$")
_STYLE_BAD = ": its style in QGIS could not be read"
_OTHER_GONE = "its layer is no longer in the project; left out."
_OTHER_KIND = "not a point, line or polygon layer; left out."

MISSING_LINE = "Layer not in the project"
MISSING_SOURCE = "removed, renamed or moved"


class RowState(NamedTuple):
    """What the dock knows of a row besides the model."""
    value: dict                        # row.value()
    name: str                          # the row's shown name (its name label's text)
    missing: bool                      # row.is_missing()
    layer_name: str = ""               # its layer's name ("" gone / none)
    table_name: str = ""               # its water-level table's name (exploration rows)
    labels: Tuple[str, ...] = ()       # surface rows: every label the build may give it (surface_labels)
    table_bad: Tuple[Tuple[str, str], ...] = ()   # exploration rows whose table has a not-number warning: up to
    #                                    CARD_ITEMS + 1 (exploration name, '"text"') of its rows whose level is a text
    #                                    but not a number


def shown(w: str) -> str:
    """A model warning as the status line shows it (OLD_PLACES rewritten)."""
    for old, new in OLD_PLACES:
        w = w.replace(old, new)
    return w


def _plural(n: int, one: str, many: str) -> str:
    return f"{n:,} {one if n == 1 else many}"


def _items(rows: Sequence[Tuple[str, str]], total: Optional[int] = None) -> Tuple[List[Tuple[str, str, str]], int]:
    """At most CARD_ITEMS (term, value, "") lines and how many more there are (of `total`, else of `rows`)."""
    shown_rows = [(str(a), str(b), "") for a, b in list(rows)[:CARD_ITEMS]]
    n = len(rows) if total is None else int(total)
    return shown_rows, max(0, n - len(shown_rows))


def _flag_problem(flags: Sequence[Tuple[str, str]], name: str, explorations: bool) -> Problem:
    """One problem for a row's flags: the first as "{label}: {flag} (+N more)", the card listing them (label, flag)."""
    label, flag = flags[0]
    line = f"{label}: {flag}" + (f" (+{len(flags) - 1} more)" if len(flags) > 1 else "")
    k = len({lab for lab, _f in flags})
    if explorations:
        title = f"{k} exploration{'s' if k != 1 else ''} flagged"
        tab = (("open_water", "Open Water") if all(SCREEN_FLAG.search(f) for _l, f in flags)
               else ("open_depths", "Open Depths"))
    else:
        title = f"{k} flagged"
        tab = ("open", "Open")
    items, more = _items(flags)
    return Problem(line, CardInfo(title, source=f"{name} · as read from the layer", items=items, mono=False,
                                  more=more, actions=[tab]), len(flags))


# ---------------------------------------------------------------- exploration rows
def explo_problems(model, rows: Sequence[RowState]) -> Tuple[List[List[Problem]], Set[str]]:
    """The exploration rows' problems: a missing layer (ticked rows), the flags of its plotted explorations, its table
    of water levels' values that are not numbers, a QGIS style that could not be read."""
    out: List[List[Problem]] = [[] for _ in rows]
    covered: Set[str] = set()
    warnings = list(getattr(model, "warnings", None) or []) if model is not None else []
    for i, r in enumerate(rows):
        probs = out[i]
        if r.missing and r.value.get("visible", True):
            probs.append(Problem(MISSING_LINE, CardInfo(
                MISSING_LINE, source=f"{r.name} · {MISSING_SOURCE}",
                note="Choose it again on the Layer tab, untick the row or remove it.",
                actions=[("open_layer", "Open Layer")])))
        if model is None:
            continue
        flags = [(h.label, fl) for h in model.hits if getattr(h, "layer_index", 0) == i for fl in (h.flags or [])]
        if flags:
            probs.append(_flag_problem(flags, r.name, explorations=True))
            covered |= {f"{label}: {fl}" for label, fl in flags}
        field = r.value.get("wl_table_elev_field", "")
        if r.table_name and field and r.value.get("visible", True):
            for w in warnings:
                m = _WL_BAD.match(w)
                if m is None or not w.startswith(f"{r.table_name}: ") or f" in {field} " not in w:
                    continue
                n = int(m.group("n").replace(",", ""))
                line = ("1 water level is not a number; left out" if n == 1
                        else f"{n:,} water levels are not numbers; left out")
                items, more = _items(r.table_bad, total=n)
                probs.append(Problem(line, CardInfo(
                    f"{_plural(n, 'water level', 'water levels')} left out",
                    source=f"{r.name} · table {r.table_name}, field {field}", items=items, mono=True, more=more,
                    note="Only plain numbers are read; 1,234.5 is fine.",
                    actions=[("open_water", "Open Water")]), n))
                covered.add(w)
        for w in warnings:
            if w.startswith(f"{r.name}{_STYLE_BAD}"):
                probs.append(Problem("Style not read; drawn in black", CardInfo(
                    "Style not read", source=f"{r.name} · its QGIS style", note=w,
                    actions=[("open_layer", "Open Layer")])))
                covered.add(w)
    return out, covered


# ---------------------------------------------------------------- Other features rows
def other_problems(model, rows: Sequence[RowState],
                   project_kinds: Sequence[str]) -> Tuple[List[List[Problem]], Set[str]]:
    """The Other features rows' problems: a layer gone (ticked rows), a layer of no feature kind, features left out
    for want of an elevation, the flags of its points and crossings. `project_kinds[j]`: the feature kind of row j's
    layer in the project ("" for none, or a layer of no kind: then its `layer_name` says the layer is there)."""
    out: List[List[Problem]] = [[] for _ in rows]
    covered: Set[str] = set()
    warnings = list(getattr(model, "warnings", None) or []) if model is not None else []
    gone = False
    for j, r in enumerate(rows):
        probs = out[j]
        kind = project_kinds[j] if j < len(project_kinds) else ""
        if r.missing and r.value.get("visible", True):
            if r.layer_name and not kind:
                probs.append(Problem("Not a point, line or polygon layer; left out", CardInfo(
                    "Not a point, line or polygon layer", source=r.name, actions=[("open", "Open")])))
                covered |= {w for w in warnings if w.startswith("Other points “") and w.endswith(_OTHER_KIND)
                            and f"“{r.name}”" in w}
            else:
                gone = True
                probs.append(Problem(f"{MISSING_LINE}; left out", CardInfo(
                    MISSING_LINE, source=f"{r.name} · {MISSING_SOURCE}",
                    note="Choose it again, untick the row or remove it.", actions=[("open", "Open")])))
        if model is None:
            continue
        infos = list(getattr(model, "other_layers", None) or [])
        info = infos[j] if j < len(infos) else None
        missing = list(getattr(info, "no_elevation", None) or []) if info is not None else []
        if missing:
            field = getattr(info, "elev_field", "") or "field"
            n = len(missing)
            items, more = _items([(label, "empty") for label in missing])
            probs.append(Problem(f"{n:,} left out: no {field}", CardInfo(
                f"{n:,} left out", source=f"{r.name} · {field} is empty and Where empty is Off", items=items,
                mono=True, more=more, actions=[("open", "Open")]), n))
        flags = [(p.label, fl) for p in (getattr(model, "other_points", None) or [])
                 if getattr(p, "layer_index", 0) == j for fl in (p.flags or [])]
        if flags:
            probs.append(_flag_problem(flags, r.name, explorations=False))
            covered |= {f"{label}: {fl}" for label, fl in flags}
    if gone:                                   # every missing row shows it: each such warning is covered
        covered |= {w for w in warnings if w.startswith("Other points “") and w.endswith(_OTHER_GONE)}
    return out, covered


# ---------------------------------------------------------------- the ground and the other surfaces
def ground_problems(model, dem_name: str, dist: Callable[[float], str]) -> Tuple[List[Problem], Set[str]]:
    """The Ground row's problems: the DEM's gaps along the line (`dist` writes a station as the sheet does)."""
    if model is None or not getattr(model.ground, "gaps", None):
        return [], set()
    g = model.ground
    pct = 100.0 * (1.0 - g.coverage)
    items, more = _items([(f"{dist(a)} to {dist(b)}", f"{b - a:,.0f} ft") for a, b in g.gaps])
    prob = Problem(f"No DEM data along {pct:.1f}% of the line", CardInfo(
        "No DEM data in places", source=f"{dem_name or 'The DEM'} · drawn as gaps", items=items, mono=True,
        more=more), len(g.gaps))
    covered = {w for w in (model.warnings or []) if w.startswith("No DEM data along")}
    return [prob], covered


def _surface_label(w: str) -> Optional[Tuple[str, str]]:
    """(label, the rest as a problem line) of a "Surface “X”…" warning; None for any other."""
    if not w.startswith("Surface “") or "”" not in w:
        return None
    label, rest = w[len("Surface “"):].split("”", 1)
    rest = rest[2:] if rest.startswith(": ") else rest.lstrip(" ")
    rest = rest.rstrip()
    if rest.endswith("."):
        rest = rest[:-1]
    return label, (rest[:1].upper() + rest[1:])


def surface_problems(model, rows: Sequence[RowState]) -> Tuple[List[List[Problem]], Set[str]]:
    """The surface rows' problems: a "Surface “X”" warning of the build (a raster gone, no band, no data, a model
    surface's own), matched to the ticked row whose `labels` hold X; a surface drawn along less than 99.5 % of the
    line. A units assumption is never a row's (the status line)."""
    out: List[List[Problem]] = [[] for _ in rows]
    covered: Set[str] = set()
    if model is None:
        return out, covered
    for w in model.warnings or []:
        if UNITS_WORDS in w:
            continue
        parsed = _surface_label(w)
        if parsed is None:
            continue
        label, line = parsed
        for i, r in enumerate(rows):
            if not r.value.get("visible", True) or label not in r.labels:
                continue
            title = "Surface left out" if "left out" in w.lower() else "Check this surface"
            out[i].append(Problem(line, CardInfo(title, source=r.name, note=w)))
            covered.add(w)
            break
    for sp in getattr(model, "surfaces", None) or []:
        cov = getattr(sp, "coverage", 1.0)
        if cov >= 0.995:
            continue
        for i, r in enumerate(rows):
            if r.value.get("visible", True) and sp.name in r.labels:
                out[i].append(Problem(f"Data along {cov * 100:.0f}% of the line", CardInfo(
                    "Part of the line has no data", source=f"{r.name} · {r.layer_name or sp.layer_name}",
                    note="The rest is drawn; the gaps stay blank.")))
                break
    return out, covered


def surface_labels(value: dict, position: int, name: str, layer_name: str) -> Tuple[str, ...]:
    """Every label the build may give a surface row (core.build.build_surfaces, mf6_section): its own name when it has
    one; a raster row's layer name, "<layer> band N" and "Surface <position>" (1-based among all surface rows); a
    model surface's shown name."""
    own = (value.get("name") or "").strip()
    if own:
        return (own,)
    if value.get("source") == "mf6":
        return (name,) if name else ()
    out = [f"Surface {position}"]
    if layer_name:
        out[:0] = [layer_name, f"{layer_name} band {value.get('band', 1)}"]
    return tuple(out)


# ---------------------------------------------------------------- the status line
def status_warnings(model, plan, mapped: Set[str]) -> List[str]:
    """The status line's warnings: the plan's, then the model's that no row shows, that are no note and not
    NO_POINTS (OLD_PLACES rewritten)."""
    out = list(getattr(plan, "warnings", None) or []) if plan is not None else []
    if model is not None:
        out += [shown(w) for w in (model.warnings or [])
                if w not in mapped and w != NO_POINTS and not w.startswith(NOTE_PREFIXES)]
    return out


def ready_text(model) -> str:
    """"Ready · 12 explorations, 3 points, 2 crossings, 1 area" (what the sheet shows); "Ready · ground line only"."""
    parts = []
    n = len(getattr(model, "hits", None) or [])
    if n:
        parts.append(_plural(n, "exploration", "explorations"))
    points = list(getattr(model, "other_points", None) or [])
    counts: Dict[str, int] = {}
    for p in points:
        kind = getattr(p, "kind", "point")
        counts[kind] = counts.get(kind, 0) + 1
    for kind, one, many in (("point", "point", "points"), ("crossing", "crossing", "crossings")):
        if counts.get(kind):
            parts.append(_plural(counts[kind], one, many))
    areas = len(getattr(model, "other_areas", None) or [])
    if areas:
        parts.append(_plural(areas, "area", "areas"))
    return "Ready · " + (", ".join(parts) if parts else "ground line only")
