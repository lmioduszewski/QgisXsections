"""The sheet's notes as text: the standard layout's wrapped notes (note_texts) and the compact layout's two short
lines (compact_notes), with the sources they name (tops and bottoms, screens and water levels, surfaces) per
exploration row.

Pure text (no matplotlib, no Qt): figure.py draws these (and re-exports every name, its public API), and
scales.plan() sizes the standard layout's bottom margin from them (scales.standard_block_depth).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from ..core.model import Hit, PageLayout, Plan, SectionModel, Settings, grid_drawn, layer_view
from .scales import (draws_depth_line, draws_td_label, engineer_face, fmt_in, fmt_num, frame_levels, hit_in_range,
                     ratio, runs_below)


def _finite_num(v: Optional[float]) -> bool:
    return v is not None and math.isfinite(v)


def _nb(s: str) -> str:
    return s.replace(" ", " ")


def grid_text(plan: Plan, settings: Settings) -> Tuple[str, str]:
    """("1 in major", "0.1 in minor"), or "1 × 0.5 in major" when the paper spacings differ."""
    hm_in, vm_in = plan.h_major / settings.h_scale, plan.v_major / settings.v_scale
    hn_in, vn_in = plan.h_minor / settings.h_scale, plan.v_minor / settings.v_scale
    major = f"{fmt_in(hm_in)} in major" if abs(hm_in - vm_in) < 1e-9 else f"{fmt_in(hm_in)} × {fmt_in(vm_in)} in major"
    minor = f"{fmt_in(hn_in)} in minor" if abs(hn_in - vn_in) < 1e-9 else f"{fmt_in(hn_in)} × {fmt_in(vn_in)} in minor"
    return major, minor


def _grid_words(plan: Plan, settings: Settings) -> Tuple[List[str], List[str]]:
    """The grid as the notes name it, only the sets drawn (grid_drawn; 0.3.7: a "none" set is left out): (["1 in
    major", "0.1 in minor"], ["100 × 10 ft", "10 × 1 ft"]), the words and their spans (non-breaking); both None: ([],
    []). note_texts and compact_notes both use it, so the plan sizes the standard block for the text drawn."""
    major, minor = grid_text(plan, settings)
    spans = (_nb(f"{fmt_num(plan.h_major)} × {fmt_num(plan.v_major)} ft"),
             _nb(f"{fmt_num(plan.h_minor)} × {fmt_num(plan.v_minor)} ft"))
    drawn = grid_drawn(settings)
    return ([w for w, d in zip((major, minor), drawn) if d], [t for t, d in zip(spans, drawn) if d])


def note_texts(model: SectionModel, settings: Settings, plan: Plan, page: PageLayout,
               frame: bool = True) -> List[str]:
    """The two notes under the plot of the standard layout (figure.notes_text draws them wrapped): the scales, grid
    and sheet; then the ground, the explorations, the other points and the sources. `frame` False: the screens and
    water levels of every exploration are named, also those of rows out of the range below the frame (the plan's
    estimate of the notes, made before the frame is known: never shorter than the drawn ones)."""
    H, V = settings.h_scale, settings.v_scale
    fh, fv = engineer_face(H), engineer_face(V)
    words, spans = _grid_words(plan, settings)
    parts = [
        f"HORIZONTAL {_nb(f'1 in = {fmt_num(H)} ft')} ({ratio(H)})" + (f", {fh} scale" if fh else ""),
        f"VERTICAL {_nb(f'1 in = {fmt_num(V)} ft')} ({ratio(V)})" + (f", {fv} scale" if fv else ""),
        f"VERTICAL EXAGGERATION {fmt_num(H / V)}×",
    ]
    if words:                                            # (0.3.7) only the drawn sets; both None: no GRID part
        parts.append(f"GRID {', '.join(words)} ({'; '.join(spans)})")
    parts.append(f"SHEET {page.sheet_name}")
    note2 = " · ".join(parts)
    datum = f" ({settings.vertical_datum})" if settings.vertical_datum else ""
    dem = model.dem_name or "DEM"
    note3 = f"Ground: {dem}{datum}, sampled every {fmt_num(model.ground.step)} ft."
    if model.has_explorations:
        note3 += (f" Explorations within {fmt_num(settings.tolerance_ft)} ft of the section line are "
                  "projected perpendicular onto it.")
        if settings.label_offset:
            note3 += " Labels give the distance and direction each exploration was projected onto the section line."
    for name, how, _, kind in _other_notes(model):
        if kind == "line":                               # (0.3.6) a line row's crossings
            note3 += f" {name} where they cross the section line: {how}."
        else:
            note3 += f" {name} within {fmt_num(settings.tolerance_ft)} ft of the section line: {how}."
    views = _hit_views(model, settings)
    if any(draws_depth_line(h, settings) for h in model.hits):
        note3 += " " + depth_sources_text(settings, _draws_any_td(model, settings, plan),
                                          [(n, v) for n, v, _ in views])
        if any(runs_below(h, plan.z_min, settings) for h in model.hits):
            note3 += " An arrow at the bottom of the frame: the exploration goes deeper; its TD is beside the arrow."
    sources = screens_sources(model, settings, plan.z_min, plan.z_max) if frame else screens_sources(model, settings)
    extra = [t for t in (sources, surfaces_sources(model)) if t]
    if extra:
        note3 += " " + " ".join(f"{t}." for t in extra)
    return [note2, note3]


def _draws_any_td(model: SectionModel, settings: Settings, plan: Plan) -> bool:
    """True when the sheet writes a TD anywhere: a TD label, or the TD beside a below-the-frame arrow (written even
    with TD labels off: it is the only depth shown there)."""
    return any(draws_td_label(h, settings) or (runs_below(h, plan.z_min, settings) and _finite_num(h.total_depth))
               for h in model.hits)


def _hit_views(model: SectionModel, settings: Settings) -> List[Tuple[str, Settings, List[Hit]]]:
    """(legend name, the row's view of the settings, its plotted explorations) per exploration row that is on and
    has an exploration on the section, in row order; one ("", settings, every hit) for a model without rows (made
    by hand)."""
    infos = getattr(model, "point_layers", None) or []
    if not infos:
        return [("", settings, list(model.hits))]
    out = []
    for i, info in enumerate(infos):
        hits = [h for h in model.hits if getattr(h, "layer_index", 0) == i]
        if info.on and hits:
            out.append((info.name, layer_view(settings, info.row), hits))
    return out


def layer_views(model: SectionModel, settings: Settings) -> List[Tuple[str, Settings]]:
    """(legend name, layer_view of its row) per exploration row that is on and has a plotted exploration, in row
    order; [("", settings)] for a model without rows (made by hand). The notes name each row's fields from these."""
    return [(name, view) for name, view, _ in _hit_views(model, settings)]


def _and_names(names: Sequence[str]) -> str:
    """ "A", "A and B", "A, B and C"."""
    names = list(dict.fromkeys(names))
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _merge_sources(items: Sequence[Tuple[str, str]], short: bool = False) -> str:
    """(text, row name) pairs ("" texts left out) as one source text: the text alone when every row has the same
    one; else each text with the rows it is for, in first-appearance order: "t1 in A; t2 in B and C" (`short`:
    "t1 (A); t2 (B and C)")."""
    groups: Dict[str, List[str]] = {}
    for text, name in items:
        if text:
            groups.setdefault(text, []).append(name)
    if len(groups) <= 1:
        return next(iter(groups), "")
    if short:
        return "; ".join(f"{t} ({_and_names(n)})" for t, n in groups.items())
    return "; ".join(f"{t} in {_and_names(n)}" for t, n in groups.items())


def _other_how(info: Any) -> Tuple[str, str]:
    """(standard, short) text of how an other-points row places its points. "From a field" with no field chosen
    places every point by its "Where it is empty" choice (on the ground line, or at the LIDAR)."""
    if info.elev == "lidar" or (info.elev == "field" and not info.elev_field and info.elev_empty == "lidar"):
        return "at the LIDAR elevation at each point", "at LIDAR"
    if info.elev == "field" and info.elev_field:
        tail = {"line": (", else on the ground line", ", else ground line"),
                "lidar": (", else the LIDAR elevation", ", else LIDAR")}.get(info.elev_empty, ("", ""))
        return f"at {info.elev_field}{tail[0]}", f"at {info.elev_field}{tail[1]}"
    return "on the ground line", "on the ground line"


def _other_notes(model: SectionModel) -> List[Tuple[str, str, str, str]]:
    """(legend name, how, how short, kind) per other-points row with a point on the section, in row order; kind is
    the row's (OtherLayerInfo.kind): "point", or "line" for a line row's crossings (0.3.6; a polygon row has no
    point: the legend names it)."""
    with_points = {p.layer_index for p in getattr(model, "other_points", None) or []}
    return [(info.name,) + _other_how(info) + (getattr(info, "kind", "point"),)
            for j, info in enumerate(getattr(model, "other_layers", None) or []) if j in with_points]


def screens_sources(model: SectionModel, settings: Settings, z_min: Optional[float] = None,
                    z_max: Optional[float] = None) -> str:
    """Where the screens and water levels on the sheet come from, e.g. "Screens: ScrTop to ScrBot (depths below
    the top); water levels: WL_Elev, ATD_Elev (ATD), table water_levels" ("" when none is drawn). Each exploration
    row names its own fields; rows that differ are named ("Screens: ScrTop to ScrBot (depths below the top) in A;
    …"). With the frame (`z_min`, `z_max`), a row left out of the elevation range counts only the levels and
    screens drawn inside it (scales.frame_levels: the others are not on the sheet)."""
    if not settings.screens:
        return ""
    screens: List[Tuple[str, str]] = []
    waters: List[Tuple[str, str]] = []
    for name, view, hits in _hit_views(model, settings):
        if any(h.screen_top is not None and (z_min is None or hit_in_range(h)
                                             or (_finite_num(h.screen_top) and h.screen_top >= z_min)) for h in hits):
            how = "depths below the top" if view.screen_values != "elevation" else "elevations"
            screens.append((f"{view.screen_top_field} to {view.screen_bottom_field} ({how})", name))
        sources = []
        used = {w.source for h in hits for w in frame_levels(h, z_min, z_max)}
        if view.wl_field and view.wl_field in used:
            sources.append(view.wl_field)
        if view.atd_field and view.atd_field in used:
            sources.append(f"{view.atd_field} (ATD)")
        if "table" in used:
            sources.append("a table of water levels")
        if sources:
            how = " (depths below the top)" if view.wl_values == "depth" else ""
            waters.append((", ".join(sources) + how, name))
    parts = []
    text = _merge_sources(screens)
    if text:
        parts.append(f"Screens: {text}")
    text = _merge_sources(waters)
    if text:
        parts.append(("water levels: " if parts else "Water levels: ") + text)
    return "; ".join(parts)


def surfaces_sources(model: SectionModel) -> str:
    """The rasters and model files behind the other surfaces, e.g. "Surfaces: Water table 2024 from wt_2024;
    mf6_botm band 1 (flat across each cell); Layer 1 head from F9_flowV1.hds (SP 30, step 13); Layer 2 bottom from
    F9_flowV1.disv.grb" ("" without surfaces)."""
    items = []
    for sp in getattr(model, "surfaces", None) or []:
        if getattr(sp, "detail", ""):                    # a MODFLOW 6 surface: what it is, which file, how drawn
            text = sp.detail                             # (its one parenthesis already says "flat across each cell")
        else:
            text = sp.name if sp.name.startswith(sp.layer_name) else f"{sp.name} from {sp.layer_name}"
            if sp.band > 1 and "band" not in text:
                text += f" band {sp.band}"
            if sp.mode == "cells":
                text += " (flat across each cell)"
        items.append(text)
    return ("Surfaces: " + "; ".join(items)) if items else ""


def _tops_text(settings: Settings, short: bool = False) -> str:
    """Where the tops come from, without "Tops: ": "ExploElev where available, otherwise LIDAR at the exploration"
    (`short`: "ExploElev, else LIDAR")."""
    lidar = "LIDAR" if short else "LIDAR at the exploration"
    tf, mode = settings.top_field, settings.top_mode
    if mode == "dem" or not tf:
        return lidar
    if mode == "field":
        return tf
    return f"{tf}, else {lidar}" if short else f"{tf} where available, otherwise {lidar}"


def _bottoms_text(settings: Settings, short: bool = False) -> str:
    """Where the bottoms come from, without "Bottoms: " ("" without a bottom field)."""
    b, d = settings.bottom_elev_field, settings.depth_field
    minus = "top − " if short else "top minus "
    if b and d:
        return f"{b}, else {minus}{d}" if short else f"{b} where available, otherwise {minus}{d}"
    if b:
        return b
    if d:
        return f"{minus}{d}"
    return ""


def depth_sources_text(settings: Settings, td: bool = False,
                       views: Optional[Sequence[Tuple[str, Settings]]] = None) -> str:
    """One sentence per end of the top-to-bottom lines, naming the sources configured, e.g.
    "Tops: ExploElev where available, otherwise LIDAR at the exploration. Bottoms: top minus ExploDepth."
    With `views` (layer_views: one per exploration row on the sheet), each row's fields; rows that differ are
    named: "Tops: ExploElev where available, otherwise LIDAR at the exploration in A; LIDAR at the exploration in
    B." (the same text for every row: the sentence above)."""
    views = list(views) if views else [("", settings)]
    tops = _merge_sources([(_tops_text(v), name) for name, v in views])
    bottoms = _merge_sources([(_bottoms_text(v), name) for name, v in views])
    return " ".join(p for p in (f"Tops: {tops}.", f"Bottoms: {bottoms}." if bottoms else "",
                                "TD = total depth." if td else "") if p)


class NotePart(NamedTuple):
    """One part of a compact note line (parts are joined with " · ")."""
    text: str
    rank: int = 0          # 0: always kept; when a line is too long, the highest ranks are left out first
    name: str = ""         # a name inside `text` that may be cut short with "…" (the DEM's)


def compact_notes(model: SectionModel, settings: Settings, plan: Plan, page: PageLayout) -> List[List[NotePart]]:
    """The two short note lines of the compact layout, as parts. Line 1: scales, exaggeration, grid, sheet.
    Line 2: the ground and the explorations; the depth sources, "TD = total depth" and the label offsets
    only when those marks are on the sheet (the explanations of marks on the sheet are always kept). The
    datum is in the elevation title, so it is not repeated here."""
    H, V = settings.h_scale, settings.v_scale
    fh, fv = engineer_face(H), engineer_face(V)
    words, _ = _grid_words(plan, settings)
    line1 = [NotePart(f"H 1 in = {fmt_num(H)} ft ({ratio(H)})" + (f", {fh} scale" if fh else "")),
             NotePart(f"V 1 in = {fmt_num(V)} ft ({ratio(V)})" + (f", {fv} scale" if fv else "")),
             NotePart(f"VE {fmt_num(H / V)}×", 1)]
    if words:                                            # (0.3.7) only the drawn sets; both None: no GRID part
        line1.append(NotePart(f"GRID {', '.join(words)}", 2))
    line1.append(NotePart(page.sheet_name.split(",")[0], 3))      # "Letter 11 × 8.5 in"
    dem = model.dem_name or "DEM"
    line2 = [NotePart(f"Ground: {dem}, every {fmt_num(model.ground.step)} ft", 0, dem)]
    if model.has_explorations:
        line2.append(NotePart(f"Explorations within {fmt_num(settings.tolerance_ft)} ft projected onto the line", 1))
    if any(draws_depth_line(h, settings) for h in model.hits):
        line2 += [NotePart(t, 2) for t in depth_sources_short(settings, layer_views(model, settings))]
        if _draws_any_td(model, settings, plan):
            line2.append(NotePart("TD = total depth"))
        if any(runs_below(h, plan.z_min, settings) for h in model.hits):
            line2.append(NotePart("Arrow at frame bottom: deeper, TD beside it", 0))
    if model.has_explorations and settings.label_offset:
        line2.append(NotePart("Labels: distance and direction projected onto the line"))
    for name, _, short, _ in _other_notes(model):
        line2.append(NotePart(f"{name}: {short}", 3))
    for text, rank in ((screens_sources(model, settings, plan.z_min, plan.z_max), 3), (surfaces_sources(model), 4)):
        if text:
            line2.append(NotePart(text, rank))
    return [line1, line2]


def depth_sources_short(settings: Settings, views: Optional[Sequence[Tuple[str, Settings]]] = None) -> List[str]:
    """depth_sources_text, short: ["Tops: ExploElev, else LIDAR", "Bottoms: top − ExploDepth"]; rows that differ
    are named: "Tops: ExploElev, else LIDAR (A); LIDAR (B)"."""
    views = list(views) if views else [("", settings)]
    tops = _merge_sources([(_tops_text(v, True), name) for name, v in views], short=True)
    bottoms = _merge_sources([(_bottoms_text(v, True), name) for name, v in views], short=True)
    return [t for t in (f"Tops: {tops}", f"Bottoms: {bottoms}" if bottoms else "") if t]
