"""Shared data classes: the contract between core (geometry), render (sheets) and ui.

Everything in section space is in FEET: stations and offsets along the line, and
elevations. core converts CRS units and DEM z units to feet before filling these.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field, fields
from typing import List, Optional, Tuple

SETTINGS_VERSION = 5
NO_POINTS = "No explorations layer: ground line only."   # model warning for a ground-only section

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


_MF6_TIME = re.compile(r"([1-9][0-9]*)(?:,([0-9]+))?")   # "kper" or "kper,kstp" ("kper,0" = "kper"); or "last"


class SectionError(Exception):
    """A problem the user can fix (shown in the panel as-is)."""


def clean_surface(d: object) -> Optional[dict]:
    """One stored surface (a dict) with every key present and of the right kind; None if `d` is not a dict.
    Unknown keys are dropped, wrong kinds and unknown choices take the default."""
    if not isinstance(d, dict):
        return None
    out = dict(SURFACE_DEFAULTS)
    for key, default in SURFACE_DEFAULTS.items():
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
        elif isinstance(v, str):
            out[key] = v
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
    label_offset: bool = False      # False: name only; True: "MW-3 · 40 ft N"
    label_vertical: bool = True

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
    allowed_sheets: List[str] = field(default_factory=lambda: ["letter", "tabloid"])
    tile: bool = True                  # split long sections across sheets with match lines
    export_format: str = "pdf"         # pdf | png | svg
    dpi: int = 300
    title: str = ""                    # extra title line (project name etc.)

    # --- sheet style (defaults suit colored pencil and, since version 4, leave the most room to draw:
    #     compact layout, grid filled below the section)
    grid_color: str = "green"          # green | gray
    data_color: str = "black"          # black | type
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
    """
    if not isinstance(data, dict):
        return data
    data = dict(data)
    if "surfaces" in data:
        data["surfaces"] = clean_surfaces(data["surfaces"])
    if data.pop("fill_below", None) is True and "fill_grid" not in data:
        data["fill_grid"] = "below"
    old_field = data.pop("bottom_field", None)
    old_mode = data.pop("bottom_mode", None)
    if isinstance(old_field, str) and old_field and "bottom_elev_field" not in data and "depth_field" not in data:
        if old_mode == "elevation":
            data["bottom_elev_field"] = old_field
        else:
            data["depth_field"] = old_field
    data["version"] = SETTINGS_VERSION
    return data


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
    direction: str                     # 8-point compass bearing from the line to the exploration
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
class SectionModel:
    length: float                      # ft
    vertex_stations: List[float]       # stations of every vertex, first = 0, last = length
    azimuth: float                     # degrees clockwise from north, start -> end point
    ground: GroundProfile
    hits: List[Hit]                    # sorted by station
    beyond_ends: List[str] = field(default_factory=list)   # labels within tolerance but past A or A'
    near_count: int = 0                # selected-type explorations within 2.5 x tolerance but not plotted
    warnings: List[str] = field(default_factory=list)
    section_crs_wkt: str = ""          # CRS of line_wkt and hit x/y
    line_wkt: str = ""                 # the section line in section CRS
    dem_name: str = ""
    points_name: str = ""
    dist_factor: float = 1.0           # section CRS units -> ft
    has_explorations: bool = True      # False: no explorations layer chosen (a ground line only)
    surfaces: List[SurfaceProfile] = field(default_factory=list)   # other surfaces, in drawing order

    @property
    def bend_stations(self) -> List[float]:
        return self.vertex_stations[1:-1]


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
