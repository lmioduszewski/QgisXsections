"""Field guesses for the point-layer rows of the panel (0.3.3): pure Python, no Qt widgets.

A row's fields are guessed from the field names when a layer is added to a row (and again for the fields a new layer
in a row lacks); the rows then show the guess for the user to check (ui.point_rows). Rules:
- whole names, matched case-insensitively and ignoring spaces and punctuation (_ - . # ...) and a trailing unit in
  parentheses ("GW Elev. (ft)" is GW_Elev; never a part of a name: "botqvr" is not a bottom elevation); the first
  name of a list that the layer has wins;
- the number boxes (0.3.5) take number fields and text fields (a CSV opened by OGR has only text fields): a name
  that matches a number field wins, a text field is guessed only when no number field matches and its values are
  numbers (the panel reads a few of them: `text_ok`; so a text column of a typed layer, like CDF_wells' Elevation_
  of survey sources, is not guessed), and the fallback of a box that needs a field is a number field only (no
  number field: the box shows none); other kinds of field (dates ...) never go in a number box;
- never the layer's primary key (a GeoPackage's fid column `id`): it is left out of the guesses and of the fallback
  of a box that needs a field (the first field), but a SAVED field that is the key is kept;
- a saved field the layer has is kept; a saved empty optional field stays empty (the user chose none) unless the row
  is being guessed afresh; a saved field the layer lacks is guessed; while the row is guessed afresh (a layer newly
  chosen), a field carried over that is only a text field in the new layer gives way to a number field the guesses
  match (0.3.5: with the rule above, a typed layer gets what 0.3.4 gave it);
- water: a measured level field is guessed first (depth names before elevation names); the ATD field is then of the
  same kind (one "Levels are" switch reads both), else, with no measured field, elevation names first. "Levels are"
  follows the guessed field's kind and is never changed for a saved field. A date is guessed only for a level field
  that is set.

The 0.3.2 lists lived in ui.dock, which imports them back under the same names (tests import them from there).
"""
from __future__ import annotations

import re
from typing import AbstractSet, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

# field-name guesses, most specific first
LABEL_NAMES = ["ExploName", "AESI_MapLabel", "ExploID", "Name", "MapLabel", "Label", "ID"]
TYPE_NAMES = ["ExploType_resolved", "ExploType", "Type"]
TOP_NAMES = ["ExploElev", "TopElev", "Top_Elev", "GroundElev", "GS_Elev", "SurfElev", "Elevation", "Elev"]
BOTTOM_ELEV_NAMES = ["BotElev", "BottomElev", "Bottom_Elev", "BOT_ELEV", "BtmElev", "TD_Elev", "TDElev", "BOH_Elev"]
DEPTH_NAMES = ["WellCompleteDepth", "ExploDepth", "TotalDepth", "Total_Depth", "TD", "Depth", "Depth_ft", "TD_ft",
               "Depth_BOH"]
SCREEN_TOP_NAMES = ["ScrTop", "Scr_Top", "ScreenTop", "Screen_Top", "TopScreen", "Scrn_Top", "ScTop", "Scr_Top_ft"]
SCREEN_BOTTOM_NAMES = ["ScrBot", "Scr_Bot", "ScreenBot", "Screen_Bot", "ScreenBottom", "Screen_Bottom", "BotScreen",
                       "Scrn_Bot", "ScBot", "Scr_Bot_ft"]
WL_DEPTH_NAMES = ["DepthToGW", "DTW", "Depth_to_GW", "DepthToWater", "GW_Depth"]
WL_ELEV_NAMES = ["WL_Elev", "WLElev", "WaterElev", "Water_Elev", "GWElev", "GW_Elev", "SWL_Elev", "WaterLevel", "WL"]
WL_NAMES = WL_DEPTH_NAMES + WL_ELEV_NAMES      # depths first (his AESI layer: DepthToGW 1,623 values, GW_Elev 465)
ATD_ELEV_NAMES = ["GW_Elev_ATD", "ATD_Elev", "ATDElev"]
ATD_DEPTH_NAMES = ["DepthToGW_ATD", "DTW_ATD", "ATD_Depth", "Depth_ATD"]
ATD_ANY_NAMES = ["ATD_WL", "WL_ATD", "ATD"]     # either kind: they leave "Levels are" as it is
ATD_NAMES = ATD_ELEV_NAMES + ATD_ANY_NAMES + ATD_DEPTH_NAMES   # the ATD guesses when no measured field is set
WL_DATE_NAMES = ["WL_Date", "WLDate", "MeasDate", "Meas_Date", "Date_Meas", "ExploDate"]
ATD_DATE_NAMES = ["ATD_Date", "ATDDate", "DrillDate", "Drill_Date", "Date_Drilled", "ExploDate"]
TABLE_NAME_NAMES = ["ExploName", "AESI_MapLabel", "Name", "Boring", "Well", "Location", "ID"]
TABLE_ELEV_NAMES = ["WL_Elev", "WaterElev", "Water_Elev", "GW_Elev", "Elevation", "Elev",
                    "WL_Elevation", "GW_Elevation", "WaterLevel", "WL"]    # (0.3.5: the last four, after the rest)
TABLE_DEPTH_NAMES = WL_DEPTH_NAMES         # the table's level while "Levels are" is Depths (0.3.5), before those above
TABLE_DATE_NAMES = ["Date", "WL_Date", "MeasDate", "Meas_Date"]
TABLE_KIND_NAMES = ["Kind", "WL_Kind", "WL_Type", "Type", "Status"]
OTHER_ELEV_NAMES = ["Elev_ft", "Elevation", "Elev", "SeepElev", "SpringElev", "GroundElev", "Z"]

# layer-name hints (parts of names, any case): explorations, and other points (seeps, springs)
POINT_HINTS = ("explor", "well", "boring", "bore", "cpt", "test", "pit")
OTHER_HINTS = ("seep", "spring")
SUPPLY_HINT = "supply"                  # a supply-well layer starts out of the elevation range
SUPPLY_FIELD = "WellCompleteDepth"      # ... and so does a layer with this field

# the field keys guess_point_row returns, in POINT_LAYER_DEFAULTS order
POINT_FIELD_KEYS = ("label_field", "type_field", "top_field", "bottom_elev_field", "depth_field", "screen_top_field",
                    "screen_bottom_field", "wl_values", "wl_field", "wl_date_field", "atd_field", "atd_date_field")
TABLE_FIELD_KEYS = ("wl_table_name_field", "wl_table_elev_field", "wl_table_date_field", "wl_table_kind_field")
OTHER_FIELD_KEYS = ("label_field", "type_field", "elev_field")

# (field name, kind) in layer order; kind: True a number field, False a text field, None any other kind (a date, a
# boolean ...: never in a number box). (Before 0.3.5 the second value was "is a number field"; False was "not a
# number", which a text field still is.)
Fields = Sequence[Tuple[str, Optional[bool]]]
# the text fields whose values are numbers (0.3.5): a set of names, or a function of a name (the panel reads the
# values only of a text field a guess would take); None: every text field (the pure checks)
TextOk = Union[None, AbstractSet[str], Callable[[str], bool]]

# a trailing unit in parentheses, ignored by the name matching: "(ft)", "(feet)", "(m)", "(ft MSL)", "(ft bgs)" ...
_UNIT = re.compile(r"\s*\(\s*(?:ft|feet|foot|us\s*ft|usft|m|meters?|metres?)\b[^()]*\)\s*$", re.IGNORECASE)


# ---------------------------------------------------------------- moved from ui.dock (0.3.2)
def _norm(name: str) -> str:
    """A field name as the guesses compare it: without a trailing unit in parentheses, spaces and punctuation
    (_ - . # ...), lower case ("GW Elev. (ft)" -> "gwelev"). (0.3.2-0.3.4: only _ - and spaces were ignored.)"""
    return re.sub(r"[\W_]+", "", _UNIT.sub("", name or "")).lower()


def guess_field(field_names: Iterable[str], candidates: Sequence[str]) -> str:
    """First candidate present in `field_names` (case-insensitive, ignoring spaces, punctuation and a trailing unit in
    parentheses: _norm), else ""."""
    by_norm = {}
    for name in field_names:
        by_norm.setdefault(_norm(name), name)
    for cand in candidates:
        hit = by_norm.get(_norm(cand))
        if hit:
            return hit
    return ""


def _text_ok_fn(text_ok: TextOk) -> Optional[Callable[[str], bool]]:
    if text_ok is None or callable(text_ok):
        return text_ok
    names = frozenset(text_ok)
    return lambda n: n in names


def _guess_text(texts: Sequence[str], guesses: Sequence[str], ok: Optional[Callable[[str], bool]]) -> str:
    """The first of `guesses` among the text fields `texts` whose values are numbers (`ok`; None: any), else "".
    `ok` is asked only of a field a guess matches, in the guesses' order."""
    pool = list(texts)
    while pool:
        hit = guess_field(pool, guesses)
        if not hit:
            return ""
        if ok is None or ok(hit):
            return hit
        pool.remove(hit)
    return ""


# ---------------------------------------------------------------- one box
def pick_field(fields: Fields, pk: Iterable[str], name: str, guesses: Sequence[str], numeric: bool = False,
               required: bool = False, keep_empty: bool = False, fresh: bool = False,
               text_ok: TextOk = None) -> Tuple[str, bool]:
    """(the field for one box, whether it was guessed from `guesses`), by the 0.3.2 rule of the panel's field boxes:
    keep `name` when the layer has it (the primary key counts here); an empty `name` of an optional box is kept with
    `keep_empty`; else the first of `guesses` the layer has, never a primary-key field; else, for a `required` box,
    the first field that is not the primary key; else "".
    A `numeric` box (0.3.5) takes number and text fields (`fields` kinds True and False), number fields first: a guess
    that matches a number field wins, a text field is guessed only when no number field matches and `text_ok` says
    its values are numbers (TextOk; None: any text field), and the fallback of a `required` box is the first number
    field (a text field only by its name; no number field: ""). So a layer with typed fields gets what 0.3.4 gave it
    (its text columns hold texts). With `fresh` (the box is guessed afresh: a layer or table newly chosen, `name`
    carried over from the one before) a `name` that is only a text field here gives way to a number field the guesses
    match; a saved text field is otherwise kept (it is his choice, whatever its values)."""
    pk = set(pk or ())
    if numeric:
        every = [n for n, kind in fields if kind is not None]          # number and text fields, in layer order
        numbers = [n for n, kind in fields if kind]
        texts = [n for n in every if n not in set(numbers)]
    else:
        every = numbers = [n for n, _kind in fields]
        texts = []
    if name and name in every:
        if numeric and fresh and name not in numbers:
            guess = guess_field([n for n in numbers if n not in pk], guesses)
            if guess:
                return guess, True
        return name, False
    if not name and not required and keep_empty:
        return "", False
    guess = guess_field([n for n in numbers if n not in pk], guesses)
    if not guess and texts:
        guess = _guess_text([n for n in texts if n not in pk], guesses, _text_ok_fn(text_ok))
    if guess:
        return guess, True
    names = [n for n in numbers if n not in pk]
    if required and names:
        return names[0], False
    return "", False


def _kind_of(name: str, depth_names: Sequence[str], elev_names: Sequence[str]) -> str:
    """"depth" or "elevation" when `name` is one of the names of that kind, else ""."""
    n = _norm(name)
    if n in {_norm(x) for x in depth_names}:
        return "depth"
    if n in {_norm(x) for x in elev_names}:
        return "elevation"
    return ""


def _esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _plural(kind: str) -> str:
    return "depths" if kind == "depth" else "elevations"


# ---------------------------------------------------------------- whole rows
def guess_point_row(fields: Fields, pk: Set[str], layer_name: str, saved: Optional[dict] = None,
                    guess_fields: bool = True, text_ok: TextOk = None) -> Tuple[dict, str]:
    """The field keys of an exploration row (POINT_FIELD_KEYS: label_field ... atd_date_field and wl_values) for a
    layer with `fields` ((name, kind) in layer order: Fields) and primary key `pk`, and the hint "Guessed from the field
    names (check them): ..." ("" when nothing was guessed). `saved`: the row's stored keys (None: a new row, every
    box guessed); a saved empty optional field stays empty unless `guess_fields`. `text_ok`: the text fields whose
    values are numbers (pick_field). `layer_name` is not used by the field rules (the elevation-range guess is
    guess_in_range)."""
    keep = saved is not None and not guess_fields
    saved = saved or {}
    pk = set(pk or ())
    got: Dict[str, str] = {}
    guessed: Dict[str, bool] = {}

    def box(key, guesses, numeric=False, required=False):
        got[key], guessed[key] = pick_field(fields, pk, str(saved.get(key) or ""), guesses, numeric=numeric,
                                            required=required, keep_empty=keep, fresh=not keep, text_ok=text_ok)

    box("label_field", LABEL_NAMES, required=True)
    box("type_field", TYPE_NAMES)
    box("top_field", TOP_NAMES, numeric=True)
    box("bottom_elev_field", BOTTOM_ELEV_NAMES, numeric=True)
    box("depth_field", DEPTH_NAMES, numeric=True)
    box("screen_top_field", SCREEN_TOP_NAMES, numeric=True)
    box("screen_bottom_field", SCREEN_BOTTOM_NAMES, numeric=True)

    wl_values = saved.get("wl_values")
    if wl_values not in ("elevation", "depth"):
        wl_values = "elevation"
    box("wl_field", WL_NAMES, numeric=True)
    if guessed["wl_field"]:
        wl_values = _kind_of(got["wl_field"], WL_DEPTH_NAMES, WL_ELEV_NAMES) or wl_values
    if got["wl_field"]:       # the ATD level is read with the same switch: never a field of the other kind
        box("atd_field", (ATD_DEPTH_NAMES if wl_values == "depth" else ATD_ELEV_NAMES) + ATD_ANY_NAMES,
            numeric=True)
    else:
        box("atd_field", ATD_NAMES, numeric=True)
        if guessed["atd_field"]:
            wl_values = _kind_of(got["atd_field"], ATD_DEPTH_NAMES, ATD_ELEV_NAMES) or wl_values

    # a date only for a level field that is set (a saved date the layer has is kept either way)
    every = {n for n, _kind in fields}
    for date_key, level_key, guesses in (("wl_date_field", "wl_field", WL_DATE_NAMES),
                                         ("atd_date_field", "atd_field", ATD_DATE_NAMES)):
        if got[level_key]:
            box(date_key, guesses)
        else:
            name = str(saved.get(date_key) or "")
            got[date_key], guessed[date_key] = (name if name in every else ""), False
    got["wl_values"] = wl_values

    hint = ""
    if any(guessed.values()):
        main = [got[k] for k in ("label_field", "type_field", "top_field", "bottom_elev_field", "depth_field")
                if guessed[k]]
        parts = [f"<b>{_esc(', '.join(main))}</b>"] if main else []
        screens = [got[k] for k in ("screen_top_field", "screen_bottom_field") if guessed[k]]
        if screens:
            parts.append(f"screens <b>{_esc(', '.join(screens))}</b>")
        water = []
        if guessed["wl_field"]:
            text = f"water <b>{_esc(got['wl_field'])}</b> as measured {_plural(wl_values)}"
            if guessed["wl_date_field"]:
                text += f" dated by {_esc(got['wl_date_field'])}"
            water.append(text)
        if guessed["atd_field"]:
            water.append(f"ATD <b>{_esc(got['atd_field'])}</b>" if water
                         else f"water <b>{_esc(got['atd_field'])}</b> as ATD {_plural(wl_values)}")
        parts += water
        hint = "Guessed from the field names (check them): " + "; ".join(parts) + "."
    return {k: got[k] for k in POINT_FIELD_KEYS}, hint


def guess_table_fields(fields: Fields, pk: Set[str], saved: Optional[dict] = None, keep_empty: bool = False,
                       wl_values: Optional[str] = None, text_ok: TextOk = None) -> dict:
    """The four wl_table_* field keys for a water-level table with `fields` and primary key `pk` (the 0.3.2 rule):
    the exploration name and the level are needed (a guess, else the first field that is not the key; the level a
    number box: pick_field's `numeric`); the date and the kind are optional (an empty saved one stays empty with
    `keep_empty`). The level's names follow "Levels are" (`wl_values`, else the saved one, else elevations): with
    depths (0.3.5) the depth names come first (DTW ...), then the elevation names as before. `text_ok`: the text
    fields whose values are numbers (pick_field). A level that matches no name, in a table without number fields, is
    "": the box shows none and the build asks him to choose (never the name column by default)."""
    saved = saved or {}
    pk = set(pk or ())
    if wl_values not in ("elevation", "depth"):
        wl_values = saved.get("wl_values") if saved.get("wl_values") in ("elevation", "depth") else "elevation"
    level_names = (TABLE_DEPTH_NAMES + TABLE_ELEV_NAMES) if wl_values == "depth" else TABLE_ELEV_NAMES
    out = {}
    for key, guesses, numeric, required in (("wl_table_name_field", TABLE_NAME_NAMES, False, True),
                                            ("wl_table_elev_field", level_names, True, True),
                                            ("wl_table_date_field", TABLE_DATE_NAMES, False, False),
                                            ("wl_table_kind_field", TABLE_KIND_NAMES, False, False)):
        out[key] = pick_field(fields, pk, str(saved.get(key) or ""), guesses, numeric=numeric, required=required,
                              keep_empty=keep_empty, fresh=not keep_empty, text_ok=text_ok)[0]
    return out


def guess_other_row(fields: Fields, pk: Set[str], layer_name: str, saved: Optional[dict] = None,
                    guess_fields: bool = True, text_ok: TextOk = None) -> dict:
    """label_field, type_field and elev_field of an other-points row: the label is needed (a guess, else the first
    field that is not the key); the type field is not guessed ("" = every point; a saved one the layer has is kept);
    the elevation field is a number box (number or text fields, pick_field's `numeric`) guessed from
    OTHER_ELEV_NAMES (a text field only when `text_ok` says its values are numbers; an empty saved one stays empty
    when `saved` is given and not `guess_fields`)."""
    keep = saved is not None and not guess_fields
    saved = saved or {}
    pk = set(pk or ())
    label = pick_field(fields, pk, str(saved.get("label_field") or ""), LABEL_NAMES, required=True)[0]
    type_field = str(saved.get("type_field") or "")
    if type_field not in {n for n, _kind in fields}:
        type_field = ""
    elev = pick_field(fields, pk, str(saved.get("elev_field") or ""), OTHER_ELEV_NAMES, numeric=True,
                      keep_empty=keep, fresh=not keep, text_ok=text_ok)[0]
    return dict(label_field=label, type_field=type_field, elev_field=elev)


def guess_in_range(layer_name: str, field_names: Sequence[str]) -> bool:
    """Whether a new row counts toward the elevation range: not for supply wells (a layer named "...supply..." or one
    with a WellCompleteDepth field: their deep wells would stretch the sheet; they stop at the frame instead)."""
    if SUPPLY_HINT in (layer_name or "").lower():
        return False
    return _norm(SUPPLY_FIELD) not in {_norm(n) for n in field_names}


def is_point_hint(name: str) -> bool:
    """A layer named like explorations (POINT_HINTS)."""
    low = (name or "").lower()
    return any(h in low for h in POINT_HINTS)


def is_other_hint(name: str) -> bool:
    """A layer named like other points: seeps or springs (OTHER_HINTS)."""
    low = (name or "").lower()
    return any(h in low for h in OTHER_HINTS)
