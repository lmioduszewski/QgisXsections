"""Shared data classes: the contract between core (geometry), render (sheets) and ui.

Everything in section space is in FEET: stations and offsets along the line, and
elevations. core converts CRS units and DEM z units to feet before filling these.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import math
import re
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional, Tuple

SETTINGS_VERSION = 7                     # 7 (0.3.4): colours from the layer style, depth widths, grid styling
NO_POINTS = "No explorations layer: ground line only."   # model warning for a ground-only section
NO_TYPES = "(no types selected)"         # a `types` list of only this matches nothing (an empty list = all values)
NO_ATD = "(no ATD values)"               # a `wl_atd_values` list of only this: none (an empty list = automatic)
NO_VALUE_TYPE = ""                       # in `types`: the NULL-or-empty type value ("(no value)" in the panel)

# --- other surfaces (DESIGN.md decision 15): raster lines drawn besides the ground
SURFACE_STYLES = ("solid", "dash", "dot")
SURFACE_MODES = ("smooth", "cells")      # bilinear between cell centres | flat across each cell (model layers)
Z_UNIT_CHOICES = ("auto", "ft", "ftUS", "m")
SURFACE_COLORS = ("#1f6fb2", "#8c5a3c", "#2e8b57", "#7b3294", "#d95f02", "#666666", "#b8860b", "#c2185b")
SURFACE_SOURCES = ("raster", "mf6")      # a raster layer in the project | a MODFLOW 6 model (decision 19)
MF6_VARS = ("top", "botm", "head", "wt")  # model top | bottom of mf6_layer | head of mf6_layer | water table (head of
                                          # the uppermost wet layer of each cell column)
SURFACE_DEFAULTS = dict(layer_id="", band=1, name="", color=SURFACE_COLORS[0], style="solid", width=1.0,
                        mode="smooth", z_units="auto", in_range=True, marks=False, visible=True,
                        source="raster",       # raster: layer_id / band; mf6: the mf6_* keys
                        mf6_path="",           # the model's grid: a .grb, or a .disv / .dis text file (absolute path)
                        mf6_var="top",         # one of MF6_VARS
                        mf6_layer=1,           # 1-based (botm, head)
                        mf6_head_path="",      # the binary head file (.hds) for head / wt
                        mf6_time="last",       # "last" (the newest saved time), "kper" (that stress period's
                                               # last saved step) or "kper,kstp" (1-based) of a saved head record
                        mf6_crs="")            # CRS of the model coordinates (auth id or WKT); "" = the project CRS
# --- screens and water levels (decision 16)
SCREEN_VALUES = ("depth", "elevation")   # screen top / bottom fields hold depths below the top, or elevations
WL_VALUES = ("elevation", "depth")       # water level fields (and the table) hold elevations, or depths below the top
WL_LABELS = ("off", "elev", "elev_date")  # text beside each water level symbol
WL_KINDS = ("measured", "atd")           # open triangle joined to the screen | filled triangle (at time of drilling)

# --- point layers (0.3.3, DESIGN.md decision 22): exploration rows and other-points rows
POINT_LOOKS = ("black", "gray", "color")  # black (as always) | gray | color: each exploration in its colour in the
                                          # layer's own QGIS style
LOOK_GRAY = "#8a8a8a"                    # the Gray look (lines, ticks, labels, TD) and its panel swatch
OTHER_SHAPES = ("asterisk", "circle", "square", "diamond", "star", "triangle")
OTHER_ELEV = ("line", "lidar", "field")  # Ground line | LIDAR at the point | From a field
OTHER_EMPTY = ("line", "lidar", "off")   # where the field is empty: on the ground line | LIDAR | left out
OTHER_SIZE_MIN, OTHER_SIZE_MAX = 3.0, 20.0
OTHER_COLOR_DEFAULT = "#1f6fb2"          # the bold blue asterisk of a seep
# a point layer's QGIS style as XSections reads it (LayerStyle.kind, core/symbology.py)
STYLE_KINDS = ("single", "categorized", "graduated", "rule", "other", "none")

# --- page orientation (0.3.5, his request): Auto as before (each sheet landscape, then portrait), or only one
ORIENTATIONS = ("auto", "landscape", "portrait")

# --- sheet style: the grid and the depth line widths (0.3.4, DESIGN.md decision 23)
GRID_CHOICES = ("green", "gray", "custom")
GRID_STYLES = SURFACE_STYLES                     # ("solid", "dash", "dot")
GRID_PRESETS = {"green": (("#5f9a72", 0.7, "solid"), ("#a8c8b2", 0.35, "solid")),     # (major, minor):
                "gray": (("#6e6e6e", 0.7, "solid"), ("#b4b4b4", 0.35, "solid"))}      #  (colour, pt, style)
GRID_W_MIN, GRID_W_MAX = 0.1, 3.0                # Custom grid widths, pt
DEPTH_LW_BLACK, DEPTH_LW_COLOR = 0.75, 1.6       # depth lines, pt: Black and Gray rows | Color rows
DEPTH_LW_LIMITS = {"depth_lw_black": (0.25, 3.0), "depth_lw_color": (0.25, 4.0)}
_GRID_W_KEYS = ("grid_major_width", "grid_minor_width")
_GRID_COLOR_KEYS = ("grid_major_color", "grid_minor_color")
_GRID_STYLE_KEYS = ("grid_major_style", "grid_minor_style")

# One exploration row (Settings.point_layers entry), in this key order (clean_point_layer). The field keys mean what
# the flat Settings keys of the same name mean (FLAT_LAYER_KEYS), for this row's layer.
POINT_LAYER_DEFAULTS: Dict[str, Any] = dict(
    layer_id="",            # the point layer
    visible=True,           # the row's tick
    name="",                # legend name; "" = the layer's name
    look="black",           # one of POINT_LOOKS
    in_range=True,          # counts toward the automatic elevation range
    label_field="", type_field="",
    types=[],               # [] = every value incl. NULL / empty; [NO_TYPES] = none; else the ticked values
                            # ("" = the NULL-or-empty value)
    top_field="", bottom_elev_field="", depth_field="",
    screen_top_field="", screen_bottom_field="",
    screen_values="depth",  # one of SCREEN_VALUES
    wl_values="elevation",  # one of WL_VALUES
    wl_field="", wl_date_field="", atd_field="", atd_date_field="",
    wl_table_id="", wl_table_name_field="", wl_table_elev_field="", wl_table_date_field="", wl_table_kind_field="",
    wl_atd_values=[])       # [] automatic ("contains ATD"), [NO_ATD] none

# The flat per-layer Settings keys (the single-layer shorthand, used only while point_layers is empty) -> row keys
FLAT_LAYER_KEYS: Dict[str, str] = {
    "points_layer_id": "layer_id",
    **{k: k for k in ("label_field", "type_field", "types", "top_field", "bottom_elev_field", "depth_field",
                      "screen_top_field", "screen_bottom_field", "screen_values", "wl_values", "wl_field",
                      "wl_date_field", "atd_field", "atd_date_field", "wl_table_id", "wl_table_name_field",
                      "wl_table_elev_field", "wl_table_date_field", "wl_table_kind_field", "wl_atd_values")}}

# One other-points row (Settings.other_points entry: seeps, springs ...), in this key order (clean_other_point)
OTHER_POINT_DEFAULTS: Dict[str, Any] = dict(
    layer_id="", visible=True,
    name="",                # legend name; "" = the layer's name
    label_field="",
    type_field="",          # "" = every point
    types=[],               # as for explorations
    shape="asterisk",       # one of OTHER_SHAPES
    color=OTHER_COLOR_DEFAULT,
    size=7.0,               # pt, OTHER_SIZE_MIN to OTHER_SIZE_MAX
    elev="line",            # one of OTHER_ELEV
    elev_field="",          # numeric field (ft) for elev "field"
    elev_empty="line")      # one of OTHER_EMPTY


_MF6_TIME = re.compile(r"([1-9][0-9]*)(?:,([0-9]+))?")   # "kper" or "kper,kstp" ("kper,0" = "kper"); or "last"
_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
_FID = re.compile(r"-?[0-9]+")


class SectionError(Exception):
    """A problem the user can fix (shown in the panel as-is)."""


def _clean_keys(d: dict, defaults: Dict[str, Any]) -> dict:
    """`defaults` with every key of `d` that has the default's kind (in the defaults' key order). An int must be >= 1
    and a float finite and > 0; a list is kept only when every item is a str. Lists are always new lists (never the
    defaults' own)."""
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in defaults.items()}
    for key, default in defaults.items():
        if key not in d:
            continue
        v = d[key]
        if isinstance(default, bool):
            if isinstance(v, bool):
                out[key] = v
        elif isinstance(default, int):
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            if isinstance(v, int) and not isinstance(v, bool) and v >= 1:
                out[key] = v
        elif isinstance(default, float):
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0:
                out[key] = float(v)
        elif isinstance(default, list):
            if isinstance(v, list) and all(isinstance(x, str) for x in v):
                out[key] = list(v)
        elif isinstance(v, str):
            out[key] = v
    return out


def _clean_color(value: str, default: str) -> str:
    return value.lower() if _COLOR.fullmatch(value) else default


def clean_surface(d: object) -> Optional[dict]:
    """One stored surface (a dict) with every key present and of the right kind; None if `d` is not a dict.
    Unknown keys are dropped, wrong kinds and unknown choices take the default."""
    if not isinstance(d, dict):
        return None
    out = _clean_keys(d, SURFACE_DEFAULTS)
    if out["style"] not in SURFACE_STYLES:
        out["style"] = SURFACE_DEFAULTS["style"]
    if out["mode"] not in SURFACE_MODES:
        out["mode"] = SURFACE_DEFAULTS["mode"]
    if out["z_units"] not in Z_UNIT_CHOICES:
        out["z_units"] = "auto"
    if out["source"] not in SURFACE_SOURCES:
        out["source"] = "raster"
    if out["mf6_var"] not in MF6_VARS:
        out["mf6_var"] = "top"
    m = _MF6_TIME.fullmatch(out["mf6_time"].replace(" ", ""))
    if m is None:
        out["mf6_time"] = "last"
    else:
        kstp = int(m.group(2) or 0)
        out["mf6_time"] = f"{int(m.group(1))},{kstp}" if kstp else str(int(m.group(1)))
    out["width"] = min(max(out["width"], 0.25), 4.0)
    return out


def clean_surfaces(value: object) -> List[dict]:
    """A stored surfaces list, each entry cleaned (clean_surface); anything that is not a dict is dropped."""
    if not isinstance(value, list):
        return []
    return [c for c in (clean_surface(d) for d in value) if c is not None]


def clean_point_layer(d: object) -> Optional[dict]:
    """One stored exploration row (a dict) with every key of POINT_LAYER_DEFAULTS, in that order, each of the right
    kind; None if `d` is not a dict. Unknown keys are dropped (a 0.3.3 row's picked `color` too: a Color row takes its
    colours from the layer style); wrong kinds and unknown choices take the default."""
    if not isinstance(d, dict):
        return None
    out = _clean_keys(d, POINT_LAYER_DEFAULTS)
    if out["look"] not in POINT_LOOKS:
        out["look"] = "black"
    if out["screen_values"] not in SCREEN_VALUES:
        out["screen_values"] = "depth"
    if out["wl_values"] not in WL_VALUES:
        out["wl_values"] = "elevation"
    return out


def clean_point_layers(value: object) -> List[dict]:
    """A stored list of exploration rows, each cleaned (clean_point_layer); anything that is not a dict is dropped."""
    if not isinstance(value, list):
        return []
    return [c for c in (clean_point_layer(d) for d in value) if c is not None]


def clean_other_point(d: object) -> Optional[dict]:
    """One stored other-points row with every key of OTHER_POINT_DEFAULTS, in that order (None if not a dict):
    unknown choices and bad colours take the default, the size is clamped to OTHER_SIZE_MIN..OTHER_SIZE_MAX pt (not
    a number: 7 pt)."""
    if not isinstance(d, dict):
        return None
    out = _clean_keys(d, OTHER_POINT_DEFAULTS)
    for key, choices in (("shape", OTHER_SHAPES), ("elev", OTHER_ELEV), ("elev_empty", OTHER_EMPTY)):
        if out[key] not in choices:
            out[key] = OTHER_POINT_DEFAULTS[key]
    out["color"] = _clean_color(out["color"], OTHER_COLOR_DEFAULT)
    size = d.get("size")
    if isinstance(size, (int, float)) and not isinstance(size, bool) and math.isfinite(size):
        out["size"] = min(max(float(size), OTHER_SIZE_MIN), OTHER_SIZE_MAX)
    else:
        out["size"] = float(OTHER_POINT_DEFAULTS["size"])
    return out


def clean_other_points(value: object) -> List[dict]:
    """A stored list of other-points rows, each cleaned (clean_other_point); non-dicts dropped."""
    if not isinstance(value, list):
        return []
    return [c for c in (clean_other_point(d) for d in value) if c is not None]


def _width(value: object) -> Optional[float]:
    """A stored width as a float, or None when it is not a finite number (a bool is not a number here)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def clean_orientation(value: object) -> str:
    """A page orientation as one of ORIENTATIONS: "auto", "landscape" or "portrait" (case and spaces ignored);
    anything else is "auto"."""
    v = value.strip().lower() if isinstance(value, str) else ""
    return v if v in ORIENTATIONS else "auto"


def clean_sheet_style(data: dict) -> None:
    """In place, the sheet-style keys of stored settings: an unknown grid_color is dropped (the default, Green, then
    applies); a grid colour that is not "#rrggbb" is dropped, else lower-cased; a width that is not a finite number
    (or is a bool) is dropped, else clamped (grid 0.1-3, depth_lw_black 0.25-3, depth_lw_color 0.25-4); an unknown
    grid style is dropped; grid_custom_used must be a bool. The page orientation (0.3.5) is cleaned too: an unknown
    one is "auto" (clean_orientation). Keys that are absent stay absent."""
    if "orientation" in data:
        data["orientation"] = clean_orientation(data["orientation"])
    if "grid_color" in data and data["grid_color"] not in GRID_CHOICES:
        del data["grid_color"]
    for key in _GRID_COLOR_KEYS:
        if key in data:
            v = data[key]
            if isinstance(v, str) and _COLOR.fullmatch(v):
                data[key] = v.lower()
            else:
                del data[key]
    limits = dict.fromkeys(_GRID_W_KEYS, (GRID_W_MIN, GRID_W_MAX))
    limits.update(DEPTH_LW_LIMITS)
    for key, (lo, hi) in limits.items():
        if key in data:
            w = _width(data[key])
            if w is None:
                del data[key]
            else:
                data[key] = min(max(w, lo), hi)
    for key in _GRID_STYLE_KEYS:
        if key in data and data[key] not in GRID_STYLES:
            del data[key]
    if "grid_custom_used" in data and not isinstance(data["grid_custom_used"], bool):
        del data["grid_custom_used"]


def grid_spec(s: Any) -> Tuple[Tuple[str, float, str], Tuple[str, float, str]]:
    """((major colour, width pt, style), (minor ...)) the sheet and the preview draw: a preset's, or (custom) the
    grid_major_* / grid_minor_* keys, cleaned (bad colour -> the Green one, width clamped to GRID_W_MIN..MAX, unknown
    style -> solid); an unknown grid_color -> Green."""
    choice = getattr(s, "grid_color", "green")
    if choice != "custom":
        return GRID_PRESETS.get(choice, GRID_PRESETS["green"]) if isinstance(choice, str) else GRID_PRESETS["green"]
    out = []
    for part, (color0, width0, _style0) in zip(("major", "minor"), GRID_PRESETS["green"]):
        color = getattr(s, f"grid_{part}_color", color0)
        width = _width(getattr(s, f"grid_{part}_width", width0))
        style = getattr(s, f"grid_{part}_style", "solid")
        out.append((color.lower() if isinstance(color, str) and _COLOR.fullmatch(color) else color0,
                    width0 if width is None else min(max(width, GRID_W_MIN), GRID_W_MAX),
                    style if style in GRID_STYLES else "solid"))
    return out[0], out[1]


def depth_widths(s: Any) -> Tuple[float, float]:
    """(Black and Gray width, Color width) in pt, clamped to DEPTH_LW_LIMITS; not a finite number -> the default."""
    out = []
    for key, default in (("depth_lw_black", DEPTH_LW_BLACK), ("depth_lw_color", DEPTH_LW_COLOR)):
        lo, hi = DEPTH_LW_LIMITS[key]
        w = _width(getattr(s, key, default))
        out.append(default if w is None else min(max(w, lo), hi))
    return out[0], out[1]


def clean_hidden(value: object) -> List[str]:
    """The stored left-off list (Settings.hidden_points): the entries "LINEKEY|LAYERID|FID" with a line key, a layer
    id and a whole-number feature id (written as int() writes it), sorted and without repeats; anything else is
    dropped."""
    if not isinstance(value, list):
        return []
    out = set()
    for v in value:
        if not isinstance(v, str):
            continue
        parts = v.rsplit("|", 2)
        if len(parts) != 3:
            continue
        line, layer, fid = parts
        if line and layer and _FID.fullmatch(fid):
            out.add(f"{line}|{layer}|{int(fid)}")
    return sorted(out)


@dataclass
class Settings:
    # --- section line: either a feature from a line layer, or a line drawn on the map
    line_layer_id: str = ""
    line_fid: Optional[int] = None
    line_wkt: str = ""              # drawn line, in line_crs_authid
    line_crs_authid: str = ""
    start_label: str = "A"
    end_label: str = "A'"

    # --- ground surface
    dem_layer_id: str = ""
    dem_band: int = 1
    dem_z_units: str = "auto"       # auto | ft | ftUS | m
    vertical_datum: str = "NAVD88"  # text only, printed in axis titles and notes

    # --- other surfaces: raster lines besides the ground (water levels, model layers), drawn in list order.
    #     Each entry is a dict with the keys of SURFACE_DEFAULTS (see clean_surface).
    surfaces: List[dict] = field(default_factory=list)

    # --- explorations
    points_layer_id: str = ""
    label_field: str = ""
    type_field: str = ""
    types: List[str] = field(default_factory=list)   # empty list = all values
    tolerance_ft: float = 150.0
    label_offset: bool = False      # False: name only; True: "MW-3 · 40 ft S" (projected 40 ft south)
    label_vertical: bool = True
    # --- several point layers (0.3.3). The flat per-layer keys above and below (points_layer_id, label_field ...
    #     wl_atd_values: FLAT_LAYER_KEYS) are the single-layer shorthand, used only while point_layers is empty:
    #     read the rows through layer_rows(), never point_layers directly. tolerance_ft, the label options, the
    #     depth-line and top rules, zero_is_missing, td_label, screens and wl_label stay shared by every row.
    point_layers: List[dict] = field(default_factory=list)   # exploration rows (POINT_LAYER_DEFAULTS), panel order
    other_points: List[dict] = field(default_factory=list)   # other-points rows (OTHER_POINT_DEFAULTS), panel order
    hidden_points: List[str] = field(default_factory=list)   # explorations he left off: "LINEKEY|LAYERID|FID", sorted

    # --- optional top-to-bottom line (DESIGN.md decision 2: each exploration uses the table where it
    #     has a usable value, else LIDAR for the top and top - depth for the bottom)
    depth_line: bool = True
    top_mode: str = "field_then_dem"   # field_then_dem | dem | field
    top_field: str = ""                # optional collar / top-of-well elevation field
    top_max_diff_ft: float = 25.0      # field value further than this from LIDAR -> use LIDAR, flag it
    zero_is_missing: bool = True       # shapefiles store null numbers as 0
    bottom_elev_field: str = ""        # optional bottom elevation field (ft)
    depth_field: str = ""              # optional total depth below the top field (ft)
    td_label: bool = True              # write "TD 50'" under the bottom of each drawn line

    # --- screens and water levels (decision 16). Water levels are elevations (ft), or depths below the exploration
    #     top (wl_values). A measured level is an open
    #     triangle joined by a leader to the middle of the screen; an ATD level (water seen at the time of
    #     drilling) is a filled triangle on the exploration line. Several levels per exploration come from a
    #     table with one row per level.
    screens: bool = True               # draw screens and water levels (when any of their fields is set)
    screen_top_field: str = ""
    screen_bottom_field: str = ""
    screen_values: str = "depth"       # depth (below the exploration top) | elevation
    wl_values: str = "elevation"       # elevation | depth (below the exploration top): every water level value
    wl_field: str = ""                 # measured water level, on the explorations layer
    wl_date_field: str = ""
    atd_field: str = ""                # ATD water level, on the explorations layer
    atd_date_field: str = ""
    wl_table_id: str = ""              # optional table (no geometry needed): one row per water level
    wl_table_name_field: str = ""      # matches the explorations' label field (case and spaces ignored)
    wl_table_elev_field: str = ""
    wl_table_date_field: str = ""
    wl_table_kind_field: str = ""      # no kind field: every table row is an ATD level
    wl_atd_values: List[str] = field(default_factory=list)   # kind values drawn as ATD; empty: those containing "ATD"
    wl_label: str = "off"              # off | elev | elev_date

    # --- scales and grid (feet per paper inch)
    h_scale: float = 1000.0
    v_scale: float = 50.0
    grid_auto: bool = True             # major = 1 in, minor = 0.1 in
    h_major: float = 1000.0
    h_minor: float = 100.0
    v_major: float = 50.0
    v_minor: float = 5.0
    z_mode: str = "auto"               # auto | manual
    z_min: float = 0.0
    z_max: float = 100.0
    below_in: float = 1.0              # grid kept below the lowest point, paper inches
    distance_labels: str = "feet"      # feet | station

    # --- sheet and output
    sheet: str = "smallest"            # smallest | letter | tabloid | ansic | archc | ansid | archd | custom
    orientation: str = "auto"          # auto | landscape | portrait (ORIENTATIONS; a custom page has none)
    allowed_sheets: List[str] = field(default_factory=lambda: ["letter", "tabloid"])
    tile: bool = True                  # split long sections across sheets with match lines
    export_format: str = "pdf"         # pdf | png | svg
    dpi: int = 300
    title: str = ""                    # extra title line (project name etc.)

    # --- sheet style (defaults suit colored pencil and, since version 4, leave the most room to draw:
    #     compact layout, grid filled below the section). The grid defaults to Green and the depth lines to
    #     0.75 pt (Black, Gray) and 1.6 pt (Color): the look of 0.3.3, so an older project draws as before.
    grid_color: str = "green"          # green | gray | custom (GRID_CHOICES)
    # Custom grid (grid_spec): always stored, even under a preset (the remembered Custom values)
    grid_major_color: str = GRID_PRESETS["green"][0][0]
    grid_major_width: float = GRID_PRESETS["green"][0][1]     # pt, GRID_W_MIN..GRID_W_MAX
    grid_major_style: str = GRID_PRESETS["green"][0][2]       # solid | dash | dot (GRID_STYLES)
    grid_minor_color: str = GRID_PRESETS["green"][1][0]
    grid_minor_width: float = GRID_PRESETS["green"][1][1]
    grid_minor_style: str = GRID_PRESETS["green"][1][2]
    grid_custom_used: bool = False     # Custom chosen once in this project (later ones keep his values)
    depth_lw_black: float = DEPTH_LW_BLACK   # pt, 0.25-3: Black and Gray depth lines (depth_widths)
    depth_lw_color: float = DEPTH_LW_COLOR   # pt, 0.25-4: Color depth lines
    shade_below: bool = False
    show_bends: bool = True            # dashed line + "BEND" at each bend of the section line
    compact_layout: bool = True        # one-line title, end letters inline, short notes beside the scale bar
    edge_margin_in: float = 0.5        # clear strip at the paper edge, in: 0.5 (any printer) or 0.3 (most lasers)
    show_notes: bool = True            # the notes under the section (scales, grid, sources)
    fill_grid: str = "below"           # off | below | both: extend the grid by whole majors to use the sheet height

    version: int = SETTINGS_VERSION

    def effective_grid(self) -> Tuple[float, float, float, float]:
        """(h_major, h_minor, v_major, v_minor) in feet."""
        if self.grid_auto:
            return self.h_scale, self.h_scale / 10.0, self.v_scale, self.v_scale / 10.0
        return self.h_major, self.h_minor, self.v_major, self.v_minor

    @property
    def vertical_exaggeration(self) -> float:
        return self.h_scale / self.v_scale

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> "Settings":
        data = migrate_settings(json.loads(text or "{}"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def migrate_settings(data: dict) -> dict:
    """Stored settings (a JSON object) from an older version -> the current keys. Unknown keys are left
    for the caller to drop.

    Version 1 had one bottom field read either as a depth or as an elevation (bottom_mode); version 2
    has a bottom elevation field and a total depth field, both optional. Version 3 replaces the
    fill_below checkbox with fill_grid (off | below | both). Version 4 only changes two defaults
    (compact_layout True, fill_grid "below"): a value stored by any version is kept as it is (a version 3
    project stores both, so it keeps its look), and a key the stored settings do not have takes the
    current default (Settings.from_json and settings_store.load fill in only the keys present).

    Versions 1 and 2 stored neither layout key, so they get the current defaults. Their fill_below
    checkbox counts only when ticked ("below"): unticked was simply the default of its day, and keeping it
    as "off" would give them the compact layout without the fill, neither their old look nor the new one.

    Version 5 only adds keys (other surfaces, screens and water levels), which older settings take at their
    defaults: nothing new is drawn until it is set up. A stored surfaces list is cleaned (clean_surfaces).

    Version 6 (0.3.3) keeps the explorations as rows (point_layers), adds other points (other_points) and the
    explorations he left off (hidden_points). A stored single explorations layer (the flat keys points_layer_id,
    label_field ... wl_atd_values: FLAT_LAYER_KEYS) becomes the first row, drawn in black under the layer's own name,
    ticked and in the elevation range, with the same fields, types and water-level table, so an older project looks
    exactly as it did; the flat keys are then dropped (the rows are the one source). Settings that have rows drop the
    flat keys too. Without rows and without a layer the flat keys are left as stored (they draw nothing). The bottom
    field step above runs first, so version 1 settings fold too.

    Version 7 (0.3.4) takes "Data lines" (data_color: black | type) out of Sheet style: each exploration row is drawn
    Black, Gray or Color, and Color takes each exploration's colour from the layer's own QGIS style. Settings stored
    with "By type" switch their Black rows to Color (Gray and Color rows are kept); "black" changes nothing; the key
    is dropped either way. This runs after the version 6 fold, so a flat older project with By type gets its row
    first and converts too. Running it again changes nothing. The new grid keys (the Custom grid's colours, widths and
    line styles) and the depth line widths take their defaults when absent (the Green grid, 0.75 pt for Black and
    Gray depth lines, 1.6 pt for Color), so an older project draws as before.

    Whatever the version, the stored sheet-style keys (the grid choice, the Custom grid's colours, widths and line
    styles, the depth line widths) are cleaned first (clean_sheet_style): a bad value is dropped (its default then
    applies) or clamped. The page orientation (0.3.5, no version step: a key older settings lack takes its default,
    Auto, the search of every earlier version) is cleaned there too: an unknown one is "auto".
    """
    if not isinstance(data, dict):
        return data
    data = dict(data)
    if "surfaces" in data:
        data["surfaces"] = clean_surfaces(data["surfaces"])
    clean_sheet_style(data)                              # every version: bad grid / width values dropped or clamped
    if data.pop("fill_below", None) is True and "fill_grid" not in data:
        data["fill_grid"] = "below"
    old_field = data.pop("bottom_field", None)
    old_mode = data.pop("bottom_mode", None)
    if isinstance(old_field, str) and old_field and "bottom_elev_field" not in data and "depth_field" not in data:
        if old_mode == "elevation":
            data["bottom_elev_field"] = old_field
        else:
            data["depth_field"] = old_field
    # version 6: the single explorations layer of older settings becomes the first row
    rows = data.get("point_layers")
    has_rows = isinstance(rows, list) and len(rows) > 0
    pid = data.get("points_layer_id")
    if not has_rows and isinstance(pid, str) and pid:
        flat = {FLAT_LAYER_KEYS[k]: data[k] for k in FLAT_LAYER_KEYS if k in data}
        data["point_layers"] = [clean_point_layer(flat)]      # black, the layer's name, ticked, in the range
        for k in FLAT_LAYER_KEYS:
            data.pop(k, None)
    elif has_rows:
        for k in FLAT_LAYER_KEYS:                            # one source of truth after loading: the rows
            data.pop(k, None)
    for key, clean in (("point_layers", clean_point_layers), ("other_points", clean_other_points),
                       ("hidden_points", clean_hidden)):
        if key in data:
            data[key] = clean(data[key])
    # version 7 (0.3.4): "Data lines: By type" leaves Sheet style. Its Black rows take each exploration's colour from
    # the layer's own style (look "color"); Gray and Color rows are kept. (A 0.3.3 row saved with look "color" and a
    # picked colour is Color from the layer style: the row has no colour key any more, clean_point_layer drops it.)
    if data.pop("data_color", None) == "type":
        for row in data.get("point_layers") or []:
            if isinstance(row, dict) and row.get("look") == "black":
                row["look"] = "color"
    data["version"] = SETTINGS_VERSION
    return data


# ----------------------------------------------------------------------------------- exploration rows
def row_from_flat(s: Settings) -> dict:
    """The exploration row the flat single-layer keys of `s` describe (drawn in black, the layer's own name, ticked
    and in the elevation range), cleaned."""
    return clean_point_layer({FLAT_LAYER_KEYS[k]: getattr(s, k) for k in FLAT_LAYER_KEYS})


def layer_rows(s: Settings) -> List[dict]:
    """The exploration rows of `s`, cleaned, in panel order: its point_layers; without any, the one row of the flat
    shorthand when it names a layer; else none (a ground line, and any other points)."""
    if s.point_layers:
        return clean_point_layers(s.point_layers)
    return [row_from_flat(s)] if s.points_layer_id else []


def layer_view(s: Settings, row: dict) -> Settings:
    """`s` as one row sees it: the flat per-layer keys set from `row` (lists copied), everything shared kept. Per-row
    work (find_explorations, top_and_bottom, screen_and_levels, read_wl_table ...) reads this view. `row` is a
    cleaned row (layer_rows); a key it lacks takes the row default."""
    return dataclasses.replace(s, **{k: copy.copy(row.get(v, POINT_LAYER_DEFAULTS[v]))
                                     for k, v in FLAT_LAYER_KEYS.items()})


def hit_settings(s: Settings, hit: Any) -> Settings:
    """The view (layer_view) of the row `hit` came from: the row hit.layer_index points at; when that row's layer is
    not hit.layer_id (a non-empty one), the first row of hit.layer_id; `s` itself when there is no such row."""
    rows = layer_rows(s)
    i = getattr(hit, "layer_index", 0)
    lid = getattr(hit, "layer_id", "")
    if isinstance(i, int) and 0 <= i < len(rows) and (not lid or rows[i]["layer_id"] == lid):
        return layer_view(s, rows[i])
    if lid:
        for row in rows:
            if row["layer_id"] == lid:
                return layer_view(s, row)
    return s


def line_key(s: Settings) -> str:
    """The section line the left-off list is kept for: "LAYERID#FID" for a picked feature (it wins over a drawn
    line, as in resolve_line), "drawn" for a line drawn on the map, else ""."""
    if s.line_layer_id and s.line_fid is not None:
        return f"{s.line_layer_id}#{s.line_fid}"
    return "drawn" if s.line_wkt else ""


def hidden_key(line_key: str, layer_id: str, fid: int) -> str:
    """One left-off entry (Settings.hidden_points): an exploration (layer id and feature id) on one section line."""
    return f"{line_key}|{layer_id}|{int(fid)}"


def point_legend_name(row: dict, layer_name: str) -> str:
    """A row's name in the legend and the panel: its legend name, else the layer's name."""
    return (row.get("name") or "").strip() or layer_name


def as_rows(s: Settings) -> Settings:
    """`s` as the panel and a version 6 load give it: the flat shorthand moved into point_layers (flat keys at their
    defaults); `s` itself when it has no layer at all."""
    if not s.point_layers and not s.points_layer_id:
        return s
    d = Settings()
    return dataclasses.replace(s, point_layers=layer_rows(s),
                               **{k: copy.copy(getattr(d, k)) for k in FLAT_LAYER_KEYS})


@dataclass
class GroundProfile:
    stations: List[float]              # ft from the start of the line, ascending, includes every vertex
    z: List[float]                     # ft; math.nan where the DEM has no data
    step: float                        # sampling step, ft (DEM cell size)
    gaps: List[Tuple[float, float]] = field(default_factory=list)   # (start, end) stations of nodata runs
    coverage: float = 1.0              # fraction of samples with data

    def z_at(self, station: float) -> float:
        """Linear interpolation; nan inside a gap."""
        s, z = self.stations, self.z
        if not s:
            return math.nan
        if station <= s[0]:
            return z[0]
        if station >= s[-1]:
            return z[-1]
        lo, hi = 0, len(s) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if s[mid] <= station:
                lo = mid
            else:
                hi = mid
        t = (station - s[lo]) / (s[hi] - s[lo]) if s[hi] > s[lo] else 0.0
        return z[lo] + (z[hi] - z[lo]) * t

    def nearest_valid(self, station: float) -> float:
        best, best_d = math.nan, math.inf
        for s, z in zip(self.stations, self.z):
            if not math.isnan(z) and abs(s - station) < best_d:
                best, best_d = z, abs(s - station)
        return best


@dataclass
class StyleItem:
    """One entry of a point layer's legend that has a symbol, as the sheet and the row editor read it."""
    key: str                  # the renderer's legend key (QgsLegendSymbolItem.ruleKey())
    label: str                # as the layer's legend names it; "(no value)" / "(other values)" ... when it has none
    color: str                # "#rrggbb": the symbol's colour (symbology.symbol_color, no feature)
    on: bool = True           # ticked in the Layers panel (always True for a non-checkable item)


@dataclass
class LayerStyle:
    """A point layer's QGIS style as XSections reads it (core.symbology.layer_style)."""
    kind: str = "none"        # one of STYLE_KINDS
    field: str = ""           # categorized / graduated: the class attribute (a field or an expression)
    name: str = ""            # kind "other": the renderer's name ("Embedded symbols" ...)
    # (dataclasses.field: the name `field` is this class's attribute here)
    items: List[StyleItem] = dataclasses.field(default_factory=list)   # in the layer legend's order


@dataclass
class Hit:
    """One exploration projected onto the section."""
    fid: int
    label: str                         # value of the label field
    type_value: str                    # value of the type field ("" if none)
    x: float                           # exploration location, section CRS
    y: float
    station: float                     # ft along the line to the perpendicular foot
    offset: float                      # ft from the line (always >= 0)
    side: str                          # "L" or "R" looking from start to end
    direction: str                     # 8-point compass direction of projection, from the exploration onto the
                                       # line (0.3.5; north of an E-W line: "S"); "" on the line
    ground_at_station: float           # DEM on the section line at `station`, ft (nearest valid if in a gap)
    ground_at_point: float             # DEM at the exploration itself, ft (nan if no data)
    top: Optional[float]               # ft; from the top field or LIDAR at the exploration
    top_source: str                    # field | dem | none
    bottom: Optional[float]            # ft
    in_gap: bool = False               # station falls in a DEM nodata gap
    flags: List[str] = field(default_factory=list)   # short user-facing notes
    bottom_source: str = "none"        # field (bottom elevation) | depth (top - depth) | none | shifted
                                       # (a table bottom moved with its rejected table top)
    total_depth: Optional[float] = None   # ft; the depth field, else top - bottom (for the TD label)
    screen_top: Optional[float] = None    # elevation of the top of the screen, ft (above screen_bottom)
    screen_bottom: Optional[float] = None
    water_levels: List["WaterLevel"] = field(default_factory=list)   # highest first
    # --- the exploration row it comes from (0.3.3)
    layer_index: int = 0               # index in layer_rows(settings) == index in model.point_layers
    layer_id: str = ""
    layer_name: str = ""               # the row's legend name (point_legend_name)
    look: str = "black"                # one of POINT_LOOKS
    color: str = ""                    # gray: LOOK_GRAY; color: its symbol's colour in the layer style ("" without a
                                       # symbol: drawn black); black: ""
    in_range: bool = True              # the row counts toward the automatic elevation range
    style_rank: int = -1               # color rows: the index in its row's LayerStyle.items of the symbol QGIS draws
                                       # it with; -1: none (drawn black)

    def tick_base(self, depth_line: bool) -> float:
        """Elevation the tick sits above: the ground line, raised to clear the exploration top."""
        if depth_line and self.top is not None and not math.isnan(self.top):
            return max(self.ground_at_station, self.top)
        return self.ground_at_station


@dataclass
class WaterLevel:
    """One water level of an exploration."""
    elev: float                        # ft
    kind: str = "measured"             # measured (open triangle, joined to the screen) | atd (filled triangle)
    date: str = ""                     # as the table gives it, dates written M/D/YYYY ("" if none)
    source: str = ""                   # the field, or "table" (for the points CSV)


@dataclass
class SurfaceProfile:
    """One other surface sampled along the line (a raster, or a MODFLOW 6 model surface, besides the ground)."""
    name: str                          # legend name (the surface's name, else the layer name / model default name)
    color: str
    style: str                         # solid | dash | dot
    width: float                       # line width, pt
    mode: str                          # smooth | cells
    stations: List[float]              # ft, ascending; in cells mode every cell edge appears twice (a step)
    z: List[float]                     # ft; nan where the raster has no data
    in_range: bool = True              # counts toward the automatic elevation range (else clipped at the frame)
    marks: bool = False                # water-table triangles along the line
    layer_name: str = ""               # the raster layer, or the model's name (mf6)
    band: int = 1                      # the raster band, or the model layer (mf6 botm / head; 1 otherwise)
    coverage: float = 1.0              # fraction of the line with data
    step: float = 0.0                  # sampling step (smooth) or cell size (cells), ft; mf6: median cell crossing
    source: str = "raster"             # raster | mf6
    detail: str = ""                   # mf6: what it is, where it comes from and how it is drawn, for the notes,
                                       # e.g. "Layer 1 head from F9_flowV1.hds (SP 30, step 13; flat across each
                                       # cell)"


@dataclass
class PointLayerInfo:
    """One exploration row as built (one per layer_rows entry, in that order, drawn or not)."""
    index: int
    layer_id: str
    name: str                          # legend name (point_legend_name); layer gone: the stored name, else "row N"
    layer_name: str                    # the QGIS layer's name ("" if none)
    look: str                          # one of POINT_LOOKS
    color: str                         # gray: LOOK_GRAY; else "" (a color row's colours are per hit)
    in_range: bool
    on: bool                           # ticked, with a layer chosen, and built
    row: dict                          # the cleaned row (its field names, for notes, hover and the panel)
    plotted: int = 0                   # its explorations in model.hits
    left_off: int = 0                  # ... in model.left_off
    near: int = 0                      # within 2.5 x tolerance but not plotted
    beyond: List[str] = field(default_factory=list)   # labels left out past the ends of the line
    style: Optional[LayerStyle] = None  # color rows: the layer's style as built


@dataclass
class OtherPoint:
    """One other point (a seep, a spring ...) on the section. Names shared with Hit where code is duck-typed."""
    fid: int
    label: str                         # the label field's value; "#<fid>" when blank
    type_value: str                    # "" without a type field, or for NULL
    x: float                           # section CRS
    y: float
    station: float                     # ft
    offset: float                      # ft, >= 0
    side: str                          # "L" | "R"
    direction: str                     # 8-point compass direction of projection onto the line, as Hit ("" on it)
    ground_at_station: float           # the ground line at the station (the nearest valid ground in a gap)
    ground_at_point: float             # LIDAR at the point itself (nan if none)
    z: float                           # the elevation it marks: the ground line (how "line"), the LIDAR, or the field
    how: str                           # line | lidar | field (after any fallback)
    field_value: Optional[float] = None   # the usable elevation field value (None: empty, or the row is not "field")
    fell_back: bool = False            # elev lidar / field could not be used: `how` is the fallback
    in_gap: bool = False               # station falls in a DEM nodata gap
    flags: List[str] = field(default_factory=list)
    layer_index: int = 0               # index in model.other_layers
    layer_id: str = ""
    layer_name: str = ""               # the row's legend name


@dataclass
class OtherLayerInfo:
    """One other-points row as built (one per Settings.other_points entry, in order)."""
    index: int
    layer_id: str
    name: str                          # legend name; layer gone: the stored name, else "row N"
    layer_name: str                    # the QGIS layer's name ("" if none)
    shape: str
    color: str
    size: float
    elev: str
    elev_field: str
    elev_empty: str
    on: bool                           # ticked, with a usable point layer, and built
    row: dict
    plotted: int = 0
    near: int = 0
    beyond: List[str] = field(default_factory=list)
    no_elevation: List[str] = field(default_factory=list)   # left out: field empty and "Where it is empty" = Off


@dataclass
class SectionModel:
    length: float                      # ft
    vertex_stations: List[float]       # stations of every vertex, first = 0, last = length
    azimuth: float                     # degrees clockwise from north, start -> end point
    ground: GroundProfile
    hits: List[Hit]                    # the PLOTTED explorations, sorted by (station, layer_index, label)
    beyond_ends: List[str] = field(default_factory=list)   # labels within tolerance but past A or A'
    near_count: int = 0                # selected-type explorations within 2.5 x tolerance but not plotted
    warnings: List[str] = field(default_factory=list)
    section_crs_wkt: str = ""          # CRS of line_wkt and hit x/y
    line_wkt: str = ""                 # the section line in section CRS
    dem_name: str = ""
    points_name: str = ""              # the first exploration row on: its QGIS layer's name
    dist_factor: float = 1.0           # section CRS units -> ft
    has_explorations: bool = True      # False: no exploration row on (a ground line, and any other points)
    surfaces: List[SurfaceProfile] = field(default_factory=list)   # other surfaces, in drawing order
    point_layers: List[PointLayerInfo] = field(default_factory=list)   # one per exploration row
    left_off: List[Hit] = field(default_factory=list)  # chosen but left off by him (hidden_points), sorted like hits
    other_points: List[OtherPoint] = field(default_factory=list)   # sorted by (station, layer_index, label)
    other_layers: List[OtherLayerInfo] = field(default_factory=list)  # one per other-points row
    line_key: str = ""                 # line_key(settings) it was built for

    @property
    def bend_stations(self) -> List[float]:
        return self.vertex_stations[1:-1]

    @property
    def has_points(self) -> bool:
        """Anything drawn on the section besides the lines: explorations or other points."""
        return self.has_explorations or any(o.on for o in self.other_layers)


@dataclass
class PageLayout:
    """One printed sheet. Distances in inches unless noted."""
    page_w: float
    page_h: float
    sheet_name: str                    # e.g. "Tabloid 17 x 11 in, landscape" or "Custom 24.5 x 14 in"
    plot_left: float                   # plot-area origin from the page's left edge
    plot_bottom: float                 # plot-area origin from the page's bottom edge
    plot_w: float
    plot_h: float
    x_min: float                       # ft, distance range shown on this sheet
    x_max: float
    tile_index: int = 1
    tile_count: int = 1
    match_left: Optional[float] = None    # station of the match line at the left, ft
    match_right: Optional[float] = None


@dataclass
class Plan:
    """Everything render needs besides the model: limits, grid and pages."""
    z_min: float
    z_max: float
    plot_length: float                 # ft, section length rounded up to the minor grid
    h_major: float
    h_minor: float
    v_major: float
    v_minor: float
    pages: List[PageLayout]
    fits: bool = True
    message: str = ""                  # why it does not fit / what was chosen
    lowest_z: float = math.nan         # lowest plotted point, ft
    lowest_what: str = ""              # e.g. "the bottom of MW-4"
    warnings: List[str] = field(default_factory=list)   # e.g. a manual elevation range that cuts off data
