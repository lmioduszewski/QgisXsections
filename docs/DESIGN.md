# XSections design (settings version 4)

QGIS 4.2.1 plugin (Qt 6, Python 3.12). Draw or pick a section line, sample a LIDAR DEM along it,
project explorations within a tolerance, and export the section at exact, independent horizontal
and vertical scales with a major and minor grid, for measuring with an engineer's scale and
drawing on with colored pencil.

The shared data classes are in `xsections/core/model.py`. Code against them exactly.

## Decisions from the user (2026-09-30)

1. The tick sits just above the ground line at the projected station, **raised to clear the
   exploration's top** when the top-to-bottom line is drawn (line on, and the exploration has a top
   and a bottom) and the top is higher (`render.scales.tick_base`, built on `Hit.tick_base`).
   An exploration with a top but no usable bottom gets the flag
   "no bottom elevation or depth (…): no top-to-bottom line".
2. **Top and bottom of each exploration, decided one exploration at a time** (revised in v2: most
   exploration tables have only a total depth, and either no top elevation or just a top elevation).
   The table is used first where it has actual elevations; LIDAR and the total depth fill the gaps
   (`core.explorations.top_and_bottom`, a pure function tested as a truth table). A value is *usable*
   when it is not NULL, not NaN and, with `zero_is_missing` (default on; shapefiles store an empty
   number as 0), not 0. Real data shows zeros and wrong values (ExploElev 205.6 ft where LIDAR is 660 ft).
   - **Top** (`top_mode`). `field_then_dem` (default): the table top (`top_field`) if usable and
     within `top_max_diff_ft` (default 25; 0 turns the check off) of LIDAR, or there is no LIDAR at the
     point → source `field`; otherwise **LIDAR sampled at the exploration's own x, y** (not at the
     station) → `dem`, flagged when a table value was rejected ("ExploElev 205.6 ft ignored: 469.0 ft
     from LIDAR"; when the value read as meters would be within the limit of LIDAR the flag adds
     "(205.6 m would match: XSections reads table values as feet)"); otherwise none. `dem`: LIDAR only.
     `field`: the table only (flagged when far from LIDAR, but kept).
   - **Depth.** A negative depth is used as positive (flagged); a depth of 0.05 ft or less is no depth.
   - **Bottom** (revised after review: a bottom elevation is usually worked out from the collar
     elevation, so a wrong collar makes a wrong bottom on the same datum). In order:
     1. The table top was rejected (`field_then_dem`), there is no usable depth, and the table bottom is
        below the table top → the bottom **moves with the top**: LIDAR − (table top − table bottom),
        source `shifted`, flagged ("BotElev 185.5 ft shifted with the top: 599 ft (15 ft below it, as in
        the table)").
     2. The table bottom (`bottom_elev_field`) is usable and the top is known: rejected with a flag when
        it is not more than 0.05 ft below the top. **The table comes first (user, 2026-09-30):** when the
        top is the table's own value, the table bottom is used (source `field`). Only when the top is
        *not* from the table (the table top was rejected, or tops come from LIDAR) and a usable depth
        exists is the table bottom checked against top − depth: more than `top_max_diff_ft` off →
        rejected with a flag ("BotElev 190.6 ft ignored: 469.0 ft from top minus ExploDepth
        (659.6 ft)"); not when the limit is 0.
     3. Otherwise **top − total depth** (`depth_field`) if the depth is usable and the top is known →
        source `depth`. Otherwise none.
   - When a table bottom is kept although it is more than 5 ft from top − depth, an info flag names
     both values.
   - `Hit.total_depth` = the depth field value when usable, else top − bottom when both are known.
   - Both fields are optional. Settings version 1 had one `bottom_field` read as a depth or as an
     elevation (`bottom_mode`); `model.migrate_settings` maps it to `depth_field` or
     `bottom_elev_field` (used by `Settings.from_json` and `settings_store.load`).
3. Explorations past either end of the line are **left out** (flat end caps, like QGIS's own
   elevation profile). They are listed in `SectionModel.beyond_ends`.
4. Printers: Letter and Tabloid normally, rarely a plotter. Default sheet = smallest of
   `allowed_sheets` (["letter", "tabloid"]), landscape first, then portrait. Long sections are
   **tiled** across sheets with match lines (`tile`, default on).
5. CRS: usually EPSG:2926 / EPSG:2927 (US survey feet). Treat ftUS as feet via
   `QgsUnitTypes.fromUnitToUnitFactor(unit, Qgis.DistanceUnit.Feet)` (2 ppm, negligible).
6. Labels vertical by default; name only by default.

## Decisions from the user (2026-09-30, second round: v2)

7. **Top cap.** When the top-to-bottom line is drawn and its top is more than `TOP_CAP_MIN_IN`
   (0.04 in) of paper from the ground line at the station (a projected exploration whose top does not
   sit on the drawn ground), the top gets a short horizontal bar identical to the bottom bar (width
   `CROSSBAR_IN` 0.08 in, same weight and colour). The dotted link from the ground down to a top below
   it stays. The preview decides on paper too (same caps as the sheet).
8. **Total depth label** (`td_label`, default on). "TD 50'" (whole feet when within 0.05 ft of an
   integer, else one decimal: "TD 31.5'") in 6.5 pt, horizontal, centred on the station 0.03 in under
   the bottom bar, only where the line is drawn and the total depth is known. Labels that would overlap
   another TD label, or any bar (bottom bars and top caps), drop 0.12 in to the next row, sweeping by
   station, at most 3 rows; a label with no free row is left out and `Plan.warnings` names it. Among the
   rows free of those, a label takes the one that covers least of the exploration ticks and name labels,
   then one clear of the ground line, then the highest (`scales.stack_labels`; the name labels are laid
   out by `scales.label_layout`, which figure.py draws with, so plan and sheet agree). A thin white halo
   (an outline copy underneath) keeps a label legible where a neighbour's line or the grid crosses it;
   the ground line is drawn over the halo (never broken by a label) and under the text. A label is
   never drawn outside the plot frame: it is moved in at the frame's ends to stay `TD_EDGE_IN`
   (0.045 in) clear of the frame line, and one that a manual elevation range cuts off is left out with a
   plan warning. The sheet notes say "TD = total depth."
9. **The explorations layer is optional.** With none chosen (the point box offers
   "(none: ground line only)"), `build_section` returns a model with no hits,
   `has_explorations = False` and the warning "No explorations layer: ground line only."; plan,
   preview, export and the panel work as usual (no swath on the map, no explorations sentence in the
   notes). A layer id that no longer resolves is still an error, in the panel too: when the chosen layer
   is removed, or a project's saved one is missing, the point box shows none but the panel keeps the id
   (and saves it), so it shows build_section's "no longer in the project" error until another layer, or
   none, is chosen.

## Decisions from the user (2026-10-01: sheet layout options, settings version 3)

"Push the title and the notes into the margins: more room to draw." Four options in Sheet style, any
combination. In version 3 they were all off by default (the earlier sheets, pixel for pixel); since version 4
the compact layout and the fill below are the defaults (decision 14).

10. **Compact layout** (`compact_layout`, default on since version 4; off in version 3): the title (+ the
    optional title line, " · " between) on one line; the end letters inline just above the frame with their
    compass direction ("A (S)" from the start, "A′ (N)" up to the end); two short note lines (5.8 pt, or
    5.5 pt) to the right of the horizontal graphic scale, in one band under the distance title (the bar moves
    left of the plot only as far as the notes need; on a sheet too narrow for them, the least needed parts are
    left out, never the explanation of a mark on the sheet: TD labels, label offsets); the elevation
    title on the left only (the numbers stay on both sides); the vertical graphic scale just clear of the
    right elevation numbers, with "VERTICAL" beside it. The preview keeps the standard marks.
11. **Printer edge** (`edge_margin_in`): 0.5 in (any printer, default) or 0.3 in (most laser printers):
    the clear strip at the paper edge. Every margin moves with it; no ink is ever inside it (the standard
    right margin also grows for a vertical-scale label wider than "100 ft", such as "1,000 ft").
12. **Notes on/off** (`show_notes`, default on): off leaves out the notes only (the grid, graphic scales,
    axis labels, title and a line-colour legend stay).
13. **Fill the sheet with grid** (`fill_grid`: off | below | both, default "below" since version 4, "off" in
    version 3; replaces v2's `fill_below`, which migrates to "below" or "off"): extend the elevation range by
    whole major intervals to use the sheet height, all below, or split with the larger half below (room for the
    geology). Never on a custom page (sized to the drawing), and never with a manual elevation range (since
    version 4: the sheet shows the range as typed, rounded to the major grid; the panel disables the choice).

## Decisions from the user (2026-10-01, second round: new defaults, settings version 4)

14. **Defaults: compact layout and fill below.** A new project gets `compact_layout = True` (option A: the title
    and the notes in the margins) and `fill_grid = "below"` (option D as built: whole major intervals, 1 in with
    the default grid, all added below the section). The printer edge stays 0.5 in (option B, 0.3 in, is opt-in)
    and the notes stay on (option C, notes off, is opt-in). "Above and below" remains a choice; the fill step
    stays one whole major. Version 4 changes these two defaults only, no keys. **Migration:** a value stored by
    any earlier version is kept as it is, and a key the stored settings do not have takes the current default
    (`Settings.from_json` and `settings_store.load` pass on only the keys present). A version 3 project stores
    every key, so it keeps its look (the standard layout, no fill, unless it chose otherwise). Settings from
    versions 1 and 2 (0.1.0) never had the layout options, so they get the new defaults: compact layout, fill
    below, 0.5 in edge, notes on. 0.1.0 always stored its `fill_below` checkbox; ticked it maps to "below",
    unticked it is dropped (it was only the default of its day: keeping it as "off" would give the compact layout
    without the fill, neither the old look nor the new one), so every 0.1.0 project gets "below". With the fill
    on by default, a manual elevation range is no longer filled (decision 13: typing 0 to 100 ft used to draw
    -200 to 100 ft on Letter); switching from Auto to Manual starts from the Auto limits, which include the fill,
    so the sheet does not change at the switch.

## Decisions from the user (2026-10-05: version 0.2.0, settings version 5)

15. **Other surfaces** (`Settings.surfaces`, a list of dicts, `model.SURFACE_DEFAULTS` / `clean_surface`): any
    number of rasters drawn as lines besides the ground (water-level rasters, MODFLOW layer tops and bottoms),
    each with its own raster and band, name (default: the layer name, "+ band N" for a multi-band raster),
    colour, line style (solid, dash, dot) and width, z units (as the DEM's), visibility, and:
    - `mode`: "smooth" (default: bilinear on cell centres, sampled every cell like the ground) or "cells" (flat
      across each cell with a vertical step at each cell edge the line crosses; for a raster in the section CRS
      the edges are traced exactly (`section.cells_profile`), otherwise sampled every 1/8 cell);
    - `in_range` (default on): counts toward the automatic elevation range. Off: the line is clipped at the
      frame (a deep model bottom would otherwise make the sheet taller; sections never tile vertically);
    - `marks`: water-table triangles (open, tip on the line, in the surface colour) every 2 in of paper.
    The ground stays the first surface (ticks, LIDAR tops and the fill depend on it). A surface that can't be
    drawn (raster gone, no such band, no data along the line) is left out with a warning, never an error.
    Surfaces are drawn under the data lines (z 3.0) and listed in the legend and the notes ("Surfaces: …").
    Fills between surfaces and reading a MODFLOW 6 grid directly are later steps.
16. **Screens and water levels** (`Settings.screens` and the `screen_*`, `wl_*`, `atd_*` keys). Water levels are
    **elevations** (default), or **depths below the exploration's top** (`wl_values = "depth"`, one switch for the
    measured field, the ATD field and the table; added at the user's request the same day: the CDF wells carry
    `DepthToGW`, not `GW_Elev`; a negative depth is above the top). Per exploration
    (`explorations.screen_and_levels`, pure):
    - screen top and bottom from two fields, as depths below the exploration's top (default) or elevations; a
      screen entirely beyond the top or bottom (by more than 1 ft) is left out and flagged (the values were
      most likely the other kind); one partly beyond is drawn and flagged;
    - a **measured** level (field `wl_field`, date `wl_date_field`) is an **open blue triangle**, tip on the
      level, with a short **black** line under it; when the exploration has a screen it sits on a leader that
      leaves the **middle of the screen bracket**, runs out to the left (0.15 in from the line; a second
      measured level 0.10 in further) and turns up (or down) to the level; without a screen it sits 0.09 in
      (`WL_DX_IN`) left of the exploration line, clear of it (the user, 2026-10-05);
    - an **ATD** level (water seen at the time of drilling; field `atd_field`) is a **filled blue triangle** 0.09 in
      left of the exploration line, no leader;
    - **several levels** per exploration (more than one water-bearing zone) come from a water-level table (any
      layer, no geometry needed: `wl_table_*`), one row per level, matched by name to the label field (case
      and runs of spaces ignored); its kind field decides ATD (the values in `wl_atd_values`; none chosen:
      values containing "ATD"); with no kind field every table row is ATD;
    - only the triangles are blue (`figure.WATER`); bracket, leader and the line under the triangle are black;
    - `wl_label`: off (default) | elevation ("652.8") | elevation and date ("652.8 (6/12/2025)"), 5.5 pt, left of
      the symbol;
    - a level more than 1 ft below the bottom, or more than 100 ft above the top, is left out and flagged (water
      levels are read as elevations, or depths); a depth without a top elevation is left out and flagged;
      duplicates are dropped; levels are listed highest first.
    Sizes are paper inches (`scales.BRACKET_DX_IN` 0.05, `LEADER_DX_IN` 0.15, triangle 0.075 x 0.086 in), the same
    at every scale. Screens and levels count toward the automatic elevation range and appear in the legend
    ("Screen", "Water level", "Water at time of drilling (ATD)") and the notes.
17. **The panel** (0.2.0): sections in drawing order (Line, Surfaces, Explorations, Depths, Screens & water,
    Scale & sheet, Sheet style), all **closed** when the panel is created, opened or a project is loaded (any
    number may be open); each header shows a summary chip (what is set, or in amber what is missing); field
    labels above fields, two per row; segmented buttons for short choices; set-once settings under "More". The
    look follows the user's Water Quality app (navy open-section bar).
18. **Legend.** `scales.legend_entries`: the line colours by type (as before), the other surfaces, and the screen
    and water level symbols on the sheet; labelled "Line colors:" when it holds types only, else "Legend:". It
    stands beside the scale bar (compact, or no notes) or under the notes (standard).

## Decisions from the user (2026-10-05, version 0.3.0: MODFLOW 6 surfaces)

19. **MODFLOW 6 model surfaces** (`source = "mf6"` surfaces; reader `core/mf6.py`, sampling `core/mf6_section.py`,
    panel `ui/mf6_dialog.py`). No flopy (it is not in the QGIS Python): plain numpy readers.
    - **Grids:** DISV (what the user uses), DIS and DISU (with vertices), from the binary grid file (`.grb`, every
      definition read by name) or the text input (`.disv`/`.dis`/`.disu`: CONSTANT, INTERNAL [FACTOR, IPRN],
      OPEN/CLOSE [(BINARY)] arrays, LAYERED, VERTICES, CELL2D, block-level OPEN/CLOSE, `n*value` repeats, commas).
      `LENGTH_UNITS` comes from the text file (next to a `.grb`, or found through the name files for GRB6 FILEOUT);
      XORIGIN/YORIGIN/ANGROT map model to world coordinates (X = xo + x cos a - y sin a, Y = yo + x sin a + y cos a).
      `find_model` accepts a run folder (mfsim.nam -> the GWF model -> its DIS package and the OC `HEAD FILEOUT`), a
      name file, a grid file or a head file.
    - **Heads:** the binary head file is indexed (52-byte record headers, double or single precision, a partly
      written last record ignored); one layer is read at a time. Dry (-1e30) and inactive (1e30) cells have no
      value; in NEWTON models a convertible cell whose head is at or below its bottom is dry too (a finding of the
      0.3.0 review: F9's layer-1 heads ran up to 23.6 ft below the layer bottom).
    - **What can be drawn** (`mf6_var`): the model top (top of the uppermost active cell of each column), the
      bottom of a layer, the head of a **layer** at a **stress period** (the user: a water table reader must pull a
      particular layer and stress period), and the **water table** (per column, the head of the uppermost wet
      layer). `mf6_time`: "last" (default: the newest time at which every layer is saved; a warning while the file
      is still being written), "kper" (that stress period's last saved step, so adaptive time stepping on a re-run
      does not lose the surface), or "kper,kstp".
    - **Along the line:** the grid's vertices are moved from the model CRS (`mf6_crs`, "" = the project CRS) to the
      section CRS once (cached); the line's exact stretches inside each cell are found by edge crossings and a
      midpoint test (non-convex cells work; a stretch along a shared edge goes to one cell). "smooth" (default)
      joins the cell values at the stretch midpoints; "cells" is flat across each cell. Stacked DISU nodes: the
      higher top, the lower bottom, the uppermost head with a value.
    - Default names: "Model top", "Layer 2 bottom", "Layer 1 head (SP 30)", "Water table (SP 30)" (the time when
      the head file has more than one). Notes: "Layer 1 head from F9_flowV1.hds (SP 30, step 13)". Any problem
      (file missing or locked, layer or time not in the file, a head file of another grid) leaves that surface out
      with a warning.
    - **Panel:** "+ Add MODFLOW 6..." opens a dialog: run folder or file, a summary, model top, layer bottoms and
      layer heads (checkable per layer), the water table, the time (Last saved, each stress period, each saved
      step), the model CRS, smooth or cells. Colours: top gray, bottoms a brown ramp, heads a purple ramp (dashed),
      the water table blue, dashed, with marks. A model row's editor changes the model, variable, layer, time and
      CRS. Model paths are stored relative to the project file when the project uses relative paths.
    - Caches keyed by (path, mtime, size): warm rebuilds of a section with four F9 surfaces take about 0.01 s.

## Real data the user works with (copies for tests, never touch originals)

`<scratch>/realdata/CDF_wells.shp`: 8 wells, **EPSG:4326 PointZ** (must be transformed), fields
`ExploName` (label), `ExploType` (values like "MW, EB-1W, TW, OBW"), `ExploDepth` (ft),
`ExploElev` (collar, sometimes 0 or wrong), `DepthToGW`, `GW_Elev`.
`<scratch>/realdata/cdf_lidar.tif`: 2667 x 3127, 1 ft cells, US survey feet, Float64,
no nodata value, elevations 527-700 ft, WA State Plane South (custom WKT, no EPSG code).

## Package layout

```
xsections/                      plugin folder (users: scripts/package.py zip; developers: install_dev.bat link)
  metadata.txt  __init__.py  plugin.py  icon.svg
  core/   model.py  units.py  section.py  explorations.py  build.py  mf6.py  mf6_section.py
  render/ scales.py  figure.py  export.py  pdfprefs.py  _pdf_incremental.py
  ui/     dock.py  widgets.py  mf6_dialog.py  maptools.py  preview.py  map_feedback.py  settings_store.py
tests/                          unittest; run with scripts/run_tests.bat (headless)
  fixtures.py  test_*.py
```

Owner of each area: core = geometry and data only (no matplotlib, no widgets). render = pages and
drawing (matplotlib `Figure` API only, never `pyplot`). ui = widgets, map tools, persistence.

## core API

```python
# core/units.py
def distance_factor_to_ft(crs: QgsCoordinateReferenceSystem) -> float        # raises SectionError if geographic
def detect_z_units(layer: QgsRasterLayer) -> str                              # "ft" | "ftUS" | "m" | "unknown"
def z_factor_to_ft(layer: QgsRasterLayer, setting: str) -> float              # setting: auto|ft|ftUS|m; auto uses detect, unknown -> same as CRS units

# core/section.py
def section_crs(dem: QgsRasterLayer, project: QgsProject) -> QgsCoordinateReferenceSystem
    # DEM CRS if projected, else project CRS if projected, else SectionError
def resolve_line(settings, project, crs) -> QgsGeometry
    # from line_layer_id/line_fid, or line_wkt/line_crs_authid; transformed to crs; multipart merged
    # (lineMerge) or SectionError; curves segmentized; >= 2 distinct vertices
def raster_sampler(dem, band, crs, z_factor) -> Callable[[np.ndarray, np.ndarray], np.ndarray]
    # bilinear on pixel centres, x/y in `crs` (transform to raster CRS if different), returns ft, nan for nodata/outside
    # reads WINDOWED blocks (per segment / per point cluster), never the whole raster
def ground_profile(line, sampler, step_ft, dist_factor) -> GroundProfile
    # stations every `step` plus every vertex plus the end; gaps = runs of nan

# core/explorations.py
def find_explorations(line, points_layer, settings, crs, sampler, dist_factor, project)
        -> tuple[list[Hit], list[str], int]      # hits sorted by station, beyond_ends labels, near_count
    # QgsFeatureRequest with filter expression on type_field IN (types) and a bbox prefilter;
    # transform points to crs; flat end caps; station via lineLocatePoint; side via
    # closestSegmentWithContext; direction = compass8 of (point - foot); top/bottom per decision 2;
    # flags e.g. "ExploElev 205.6 ft ignored: 454.6 ft from LIDAR", "station in a DEM gap"
def top_and_bottom(table_top, lidar, table_bottom, depth, settings) -> TopBottom
    # pure (no QGIS): (top, top_source, bottom, bottom_source, total_depth, flags) per decision 2

# core/build.py
def build_section(settings: Settings, project: QgsProject) -> SectionModel
    # resolves layers by id, runs everything above, fills warnings; raises SectionError with a
    # message fit for the panel (no DEM chosen, geographic CRS, line off the DEM, etc.);
    # no explorations layer chosen: a ground-only model (decision 9)
```

## render API

```python
# render/scales.py
SHEETS = {"letter": (11, 8.5, "Letter"), "tabloid": (17, 11, "Tabloid"), "ansic": (22, 17, "ANSI C"),
          "archc": (24, 18, "ARCH C"), "ansid": (34, 22, "ANSI D"), "archd": (36, 24, "ARCH D")}
MARGIN = dict(left=1.0, right=1.5, top=1.2, bottom=2.3)   # standard layout, 0.5 in printer edge
NOTES_MIN_W = 6.4                                          # width the scale bars + notes need (standard)
def margins(settings, z_range=None, types=()) -> dict      # left, right, top, bottom: inches, paper edge to frame
def notes_min_w(settings, types=()) -> float               # width the block under the plot needs
def plan(model: SectionModel, settings: Settings) -> Plan
```

`margins()`: the standard layout with notes keeps `MARGIN`, moved by the printer edge (0.5 in: `MARGIN`;
0.3 in: 0.2 in less on every side). The compact layout, and the bottom without notes, are added up from
what is drawn there, with scales.py's text metrics (one line of DejaVu Sans is 1 em tall as matplotlib
lays it out, 0.24 em below the baseline) plus `LAYOUT_PAD_IN` (0.03 in), rounded up to 0.01 in:
- compact top: end-letter row (0.03 in over the frame, 11 pt) + 0.05 in + title row (11 pt);
- compact bottom: ticks + numbers + distance title (23 pt) + 0.06 in + the band (scale-bar numbers,
  bar, two note lines beside it, legend rows if any);
- compact left: ticks + widest elevation number + 4 pt + elevation title (8 pt + 1.5 pt);
- compact right: ticks + widest elevation number + 0.08 in + the vertical bar and its "20 ft";
- no notes (standard): the bar 0.64 in under the frame and "HORIZONTAL" under it;
- standard right: `MARGIN` holds the vertical scale's top label up to "100 ft" (it then ends exactly at the
  printer edge); a wider one ("1,000 ft") gets 0.64 + 0.1 in + its width x `RASTER_SLACK` + the pad.
`z_range` is the elevations the sheet may label (fill included; else a five-digit number is assumed);
`types` the line-colour legend (rows at the least column width). `notes_min_w`: 6.4 (standard), the
scale bar + 0.25 + 3.6 in of notes (compact), the scale bar alone (no notes; + 2.4 in for a legend).

Rules in `plan()`:
- Grid = `settings.effective_grid()`. Plot length = `ceil(length / h_minor) * h_minor`.
- Auto z: `lo = min(ground, bottoms, tick bases, lowest TD label row)`, `hi = max(ground, tops, tick bases)`;
  `z_min = floor((lo - below_in * v_scale) / v_major) * v_major` (so `below_in` of grid stays under the
  TD labels too; `scales.td_labels` lays them out as figure.py does),
  `z_max = ceil(max(hi + 0.9 in * v_scale, label_top) / v_major) * v_major`, where `label_top` is the
  elevation the exploration labels reach (+0.1 in): long labels and stacked horizontal labels get room.
  Manual z: round min down and max up to `v_major`. Always z_max > z_min. When a manual range cuts off
  the ground, tops or bottoms (or leaves the labels no room), `Plan.warnings` says so; ticks and labels
  whose tick base is outside the range are not drawn (the data lines are clipped at the frame).
- Page need = (max(plot_w + left + right, notes_min_w + 2 x edge + 0.2), plot_h + top + bottom), with
  the margins of `margins()`.
  `sheet == "smallest"`: first of `allowed_sheets` (in size order) that fits, landscape then portrait.
  Named sheet: that sheet, landscape then portrait. `custom`: page = need rounded up to 0.25 in, min 8.5 x 5.5.
- Does not fit and `tile` is on: tile horizontally on the largest allowed sheet (or the named one), landscape.
  Core width per sheet = whole number of `h_major`; overlap = one `h_major` each side (clipped at the ends);
  `match_left/right` = core boundaries. Height must fit; otherwise `fits=False` with a message.
- Does not fit and `tile` off: `fits=False`, message names the needed size and suggests custom size, a
  larger sheet, a smaller scale, or tiling. Export refuses when `fits` is False. Never shrink to fit.
- `fill_grid`: add whole `v_major` intervals to use the sheet height (not for custom pages, not with a manual
  elevation range): "below" all under the data, "both" the larger half below, the rest above (`fill_majors`,
  `_fill`). `Plan.message` gives the plot size as filled.
- Plot area centred on the page horizontally; placed so margins are respected. Offsets snapped to 0.01 in.

```python
# render/figure.py
def draw_page(fig: Figure, model, settings, plan, page: PageLayout) -> None     # exact-scale sheet
def draw_preview(fig: Figure, model, settings, plan) -> None                  # dock preview: fits the figure, same VE
def display_label(hit, settings) -> str                                       # "MW-3" or "MW-3 · 40 ft N"
# render/export.py
def export(model, settings, plan, path: str, fmt: str = "pdf", dpi: int = 300) -> list[str]
    # pdf: one file, one page per sheet (PdfPages), then pdfprefs.add_print_prefs
    # png/svg: one file per sheet (path, or path_sheet1.png ... when tiled)
# render/pdfprefs.py
def add_print_prefs(path: str) -> bool    # /ViewerPreferences <</PrintScaling /None /PickTrayByPDFSize true>>
    # pypdf FULL rewrite (PdfWriter(clone_from=...)); NOT incremental=True (breaks Ghostscript).
    # Without pypdf: _pdf_incremental appends a catalog revision (same xref kind as the file's newest).
    # False, file untouched, for an encrypted or unparseable PDF. pypdf is never imported at import time.
```

### Drawing spec (the sheet)

- Figure size = page size in inches; `fig.add_axes([left/W, bottom/H, plot_w/W, plot_h/H])`;
  `set_xlim(page.x_min, page.x_max)`, `set_ylim(z_min, z_max)`; autoscale off; aspect "auto";
  never `bbox_inches="tight"`, `tight_layout` or `constrained_layout`; savefig with
  `rc_context({"savefig.bbox": "standard", "savefig.pad_inches": 0, "pdf.fonttype": 42, "svg.fonttype": "none"})`.
  `MultipleLocator.MAXTICKS` raised (default 1000 is too low).
- Grid: explicit lines at multiples of each interval. Minor 0.35 pt, major 0.7 pt.
  Colors: green `#a8c8b2` / `#5f9a72`, gray `#b4b4b4` / `#6e6e6e`. Frame 0.9 pt black.
- Ground: 1.1 pt black, broken at nodata; each gap has a dotted link between its edges and a small
  "NO DEM DATA" note under it. Optional light fill below ground drawn under the grid. Drawing order:
  top-to-bottom lines (3.5) < TD halo (4.4) < ground (4.45) < TD text (4.5) < ticks < labels < match notes.
- Bends: thin dashed vertical line at each bend station, "BEND" above the frame. Optional:
  `Settings.show_bends` (default on; panel: Sheet style > Draw bend lines), sheet and preview alike.
- Top-to-bottom line (if on and top and bottom exist): 0.75 pt dark gray (#2b2b2b), 1.6 pt type color if
  `data_color == "type"`; small cross-bar (0.08 in) at the bottom, and the same bar at the top when the
  top is more than 0.04 in from the ground line (decision 7). If top is below the ground at the station
  by more than 0.05 in on paper, a dotted link from the ground down to the top.
- TD label under each bottom bar (decision 8): "TD 50'", 6.5 pt, rows 0.12 in apart, at most 3.
- Tick: 0.9 pt, from `tick_base + 0.04 in` to `+0.18 in` (paper units via `ScaledTranslation`).
- Label: 7 pt, vertical by default (reads bottom to top), above the tick; labels closer than
  1.18 x font height are spread sideways with thin leader lines (minimal 1-D displacement).
  Horizontal option: staggered rows.
- Axes: distance along the bottom (feet "1,000" or stations "10+00" at each major line), elevation
  labels on **both** sides at each major line; titles "Distance along section (ft)" or
  "Station (ft)", and "Elevation (ft {datum})" on both sides.
- Above the plot: "CROSS SECTION A–A′" (+ " (SHEET n OF N)" when tiled) and optional title line;
  end letters over the true ends only, each with its 16-point compass direction below, e.g. "A (W)".
  A title line too long to sit between the end letters lifts both title lines 0.04 in (clear of the
  letters) and may run past the plot, kept within the printer edge (8.5 pt down to 7 pt, then cut short
  with "…"); a shorter one is drawn exactly as before.
  A BEND label that would overlap an end letter or another BEND label is left out (its line stays).
- Right of the plot: a vertical graphic scale 1 in tall (5 segments), labelled 0 and "50 ft".
- Below the plot, from the left safe margin: horizontal graphic scale 2 in (4 segments), then wrapped
  notes (`show_notes`; without them a line-colour legend stands beside the bar).
- Compact layout (decision 10): one title row and one end-letter row (`compact_rows_in`), the band under
  the distance title (`bottom_band`) with the bar, "HORIZONTAL" after it and `compact_notes` beside it,
  the vertical bar `vbar_dx_in` right of the frame. `compact_notes` gives each line as ranked parts
  (line 1: H and V scales, VE, grid, sheet; line 2: ground (DEM name, no datum: the elevation title has
  it), explorations, depth sources, "TD = total depth" and the label-offset explanation when those marks
  are drawn). `fit_compact_notes`: whole lines at 5.8, then 5.5 pt with the bar under the plot's left end;
  else the bar moves left (to the printer edge at most) just enough for the whole lines at 5.8, then
  5.5 pt; else `fit_note_line` shortens each line at 5.5 pt: the DEM name cut short with "…" (16
  characters kept), then parts left out one at a time, highest rank first (sheet, grid, VE; Bottoms,
  Tops, explorations), rank 0 never (scales, ground, TD, offsets; a rank-0 line still too long is cut
  short). The notes are fitted on `note_width_in` (outline width x `RASTER_SLACK`, so a PDF and a 150,
  300 or 600 dpi PNG of a sheet carry the same notes at the same size). Other text placed next to other
  text or near the paper edge is measured as the sheet draws it (`ink_width_pt`: outline widths for
  PDF/SVG, drawn at 72 dpi; for a PNG, drawn at its own dpi, Agg's width, up to ~5 % wider for small
  type at 150 dpi). (No check bar and no red print instruction: the user, 2026-10-01, checks prints by
  measuring the grid with an engineer's scale.)
  1. "HORIZONTAL 1 in = 1,000 ft (1:12,000), 10 scale · VERTICAL 1 in = 50 ft (1:600), 50 scale ·
     VERTICAL EXAGGERATION 20× · GRID 1 in major, 0.1 in minor (1,000 × 50 ft; 100 × 5 ft) · SHEET Letter 11 × 8.5 in, landscape"
     (engineer's scale face = k in {10..60} with scale/k in {0.1, 1, 10, 100, 1000}; omit if none,
     so 1 in = 5 ft names the 50 scale)
  2. "Ground: {dem name} ({datum}), sampled every {step} ft. Explorations within {tol} ft of the section
     line are projected perpendicular onto it." (+ offsets sentence only if offsets are labelled; the
     explorations sentences only with an explorations layer) + when any line is drawn, the sources
     configured: "Tops: ExploElev where available, otherwise LIDAR at the exploration. Bottoms: BotElev
     where available, otherwise top minus ExploDepth." (adapted to `top_mode` and the empty fields) +
     "TD = total depth." when TD labels are drawn.
- Tiles: match line (dashed, dark red) at `match_left/right`, drawn under the ground and the data, with
  "MATCH LINE STA 32+00 · SEE SHEET 2 OF 3" (on two lines, or smaller, when the plot is too short for it;
  always 0.1 in inside the frame); overlap band lightly shaded. The note never covers a TD label, an
  exploration tick or label or a bar when any spot allows it, and keeps off the top-to-bottom lines and
  the ground line where it can (its white halo would cut them): candidates along the line in 0.05 in
  steps are scored in that order, then by form (one line, then two, then three shorter lines), side
  (core side, then the overlap band) and nearness to mid-height (`figure._Painter._match_note`).
- Colored by type: 8 colours, then the same colours dashed, dotted and dash-dotted (legend matches).
- Notes are drawn one text per wrapped line at a fixed pitch (6.3 pt x 1.3), 0.035 in between notes.
- The left elevation title keeps the printer edge from the page edge (moved closer to the tick labels if
  needed).

## ui

- Toolbar button toggles the **XSections** dock (right). A second dock **XSections preview** (bottom)
  holds a `FigureCanvasQTAgg` + `NavigationToolbar2QT` showing `draw_preview`.
- Panel sections (0.2.0, decision 17; `ui/widgets.py`: collapsible `Section` with a summary chip, `Segmented`
  with the QComboBox API the code uses, "More" disclosures), top to bottom: Line, Surfaces (the ground row with
  the DEM, then one row per other surface with an inline editor, + Add surface, + Add all bands…), Explorations,
  Depths, Screens & water (screen fields, Screen values are Depths | Elevations, Water levels are Elevations |
  Depths, measured and ATD fields with dates, Print beside the symbol Off | Elevation | Elev. + date, More:
  water-level table), Scale & sheet, Sheet style (Grid Green | Gray, Data lines Black | By type, Printer edge
  0.5 | 0.3 in, Fill with grid Off | Below | Both; Compact layout, Notes, Bend lines, Shade below ground). All
  closed when the dock is created, reopened, or a project is loaded or cleared; never saved. The open
  header is navy (`#193340`; the palette highlight in a dark theme). Action bar: Refresh, ⋯ (Export points CSV…,
  Save line to layer), Export… The widgets start from `Settings()`.
  Widgets: `QgsMapLayerComboBox` (filtered by geometry/raster), `QgsFieldComboBox` (allow empty where
  optional), `QgsRasterBandComboBox`,
  `QgsDoubleSpinBox`. Type values: checkable list filled from `layer.uniqueValues(idx)` with counts.
  Field defaults guessed from whole names, ignoring case, `_`, `-` and spaces, never from a part of a
  name (label: ExploName, ExploID, Name, ID; type: ExploType, Type; top elevation: ExploElev, TopElev,
  Top_Elev, GroundElev, GS_Elev, SurfElev, Elevation, Elev; bottom elevation: BotElev, BottomElev,
  Bottom_Elev, BOT_ELEV, BtmElev, TD_Elev, TDElev; total depth: ExploDepth, TotalDepth, Total_Depth, TD,
  Depth, Depth_ft, TD_ft; the three elevation/depth boxes only take number fields). Guesses fill a
  fresh project or a newly chosen point layer; an optional field saved empty stays empty (none).
  Layers in a fresh project: a section line layer only by name (section, xsec, x-sec, profile,
  transect), never an arbitrary line layer; a DEM by name, else the first single-band raster not named
  like a photo or hillshade; points by name, else the first point layer (the point box also offers
  "(none: ground line only)", and a none chosen by the user is kept when layers are added). Layers added later
  (`QgsProject.layersAdded`): a box that is still empty gets the same guess from the new layers, and the
  field boxes are re-synced to the point box (it auto-selects a new layer but reports `layerChanged(None)`).
- Section line: line layer combo + feature combo, **Pick on map**, **Draw on map**, **Use selected**,
  **Reverse**, end labels. Draw tool = port of `QgsMapToolProfileCurve` (`QgsMapToolCapture`,
  CaptureLine, `layer()` returns None, emits the captured curve; snapping and CAD dock work).
  Pick tool = `QgsMapToolIdentifyFeature` / `QgsIdentifyMenu.findFeaturesOnCanvas` on line layers.
- Map feedback (`QgsRubberBand`): section line, flat-cap swath (`buffer(tol, 8, Flat, Round, 2)`),
  plotted explorations highlighted. Cleared on unload.
- Top-to-bottom line group: [x] Draw a line from top to bottom; Top from (Table, else LIDAR at the
  exploration / LIDAR at the exploration / Table only); Top elevation field; Bottom elevation field;
  Total depth field (all optional); Treat 0 as missing; Ignore a table top more than [25] ft from LIDAR;
  [x] Label total depth (TD 50'); the one-line rule "Each exploration: top from the table, else LIDAR;
  bottom from the table, else top − depth."; and a sources readout
  ("Tops: 5 ExploElev, 3 LIDAR · Bottoms: 2 BotElev, 6 top − ExploDepth, 1 none").
- Readouts under each group: length / vertices / bends / direction with azimuth (hint to Reverse if
  A′ bears 135–315°), DEM coverage and gaps, plotted count / near count / beyond ends / flags (or
  "No explorations layer: ground line only"), top and bottom sources,
  VE / plot area / elevation range / grid below lowest point / sheet and tiles / fit warning.
- Any change (including a new project or layer CRS) -> debounced (300 ms) rebuild + preview. Errors
  (`SectionError`) show in a message line, never a traceback dialog; `Plan.warnings` and model warnings
  not already in a readout show there in amber. In Auto, the disabled min / max show the auto limits.
- File errors (a PDF or CSV held open by another program) become a message-bar warning. Unreadable
  saved settings fall back to defaults value by value; a failed restore never half-loads the plugin.
- The preview toolbar has Home, Back, Forward, Pan and Zoom only (no Save: the preview is not to scale).
- **Export…**: file dialog (PDF/PNG/SVG; default name "Section A-A' H1000 V50.pdf"), then `export()`;
  message bar with the file path(s).
  **Save line to layer** (memory layer "XSections lines": start, end, h_scale, v_scale, tolerance).
  **Export points CSV** (one row per Hit, with top_source, bottom_source (field, shifted, depth or none),
  depth_ft = top − bottom, total_depth_ft, screen_top_ft, screen_bottom_ft and water_levels, e.g.
  "652.8 measured 6/12/2025; 640.1 ATD").
- Settings persist in the project: `QgsProject.writeEntry("xsections", "settings", settings.to_json())`,
  restored on project load (older versions migrated, see decisions 2 and 14).
- Qt6 rules: fully qualified enums (`Qt.AlignmentFlag.AlignLeft`), `exec()` not `exec_()`, import Qt via
  `qgis.PyQt`, no PyQt5 imports, no compiled resources (icon by file path). `unload()` removes every
  action, dock, map tool, rubber band and signal connection.

## Tests (unittest, headless)

`scripts/run_tests.bat` runs `python -m unittest discover -s tests -v` through the OSGeo4W
`python-qgis.bat` with `QT_QPA_PLATFORM=offscreen` and `QT_QPA_FONTDIR=C:\Windows\Fonts`.
`tests/fixtures.py` builds synthetic data (EPSG:2927 DEM in feet with a known plane + valley, points
at known stations/offsets, a bent line; `make_points_layer(bot_elev=True)` adds a BotElev field whose
rows each exercise one bottom rule). Export tests measure the output: 300 dpi PNG gridline
spacing = 300 ± 0.5 px, frame size = inches × 300 ± 1 px, PDF MediaBox = page × 72, PrintScaling
present; tiled output has the right page count and every page measures to scale. Real-data tests
run only when `XSECTIONS_REALDATA` points at the copied folder. `test_layout.py` draws every combination
of the layout options (compact, edge, notes, fill) on Letter landscape, Letter portrait and a tiled
Tabloid sheet: the PNG measures 300 px/in and the frame its size, the marks around the frame (titles, end
letters, BEND, axis labels and titles, scale bars, notes, legend, match notes) never overlap, and the
printer-edge strip of the PNG has no ink (the portrait case carries a title line too long for the sheet).
It also checks the compact notes (5.8 or 5.5 pt, the same text in a PDF and a PNG, the bar moved no
further than needed, TD and offset explanations kept, the DEM name cut before parts are left out), the
standard title line (unchanged when it fits, else lifted and fitted), and a plot as wide as the margins
allow at 1 in = 1,000 ft vertical ("1,000 ft" stays inside the printer edge in every layout); the version 4
defaults and migration (a version 3 project keeps its look, a version 2 one, as 0.1.0 saved it with its fill
checkbox ticked or not, gets the new defaults), that a manual range is never filled (one sheet and tiled); and, with
real data, the CDF section with the default layout on Letter landscape at 1 in = 200 / 20 ft (filled below in
whole majors to 580-700 ft, 300 px/in, the frame exact, no ink in the 0.5 in edge, no overlaps). Tests of the
standard geometry (margins, page placement, elevation limits, notes text) pin the standard layout
(`fixtures.STANDARD_LAYOUT`: `compact_layout=False, fill_grid="off"`), in their settings helpers
(`test_figure.make_settings`, `test_scales.settings`) or in the test itself.

`test_mf6.py` and `test_mf6_section.py` (0.3.0) cover the MODFLOW 6 readers and sampling with three small real
models in `tests/data/mf6` (DISV, rotated DIS, DISU; run with mf6 6.7.0, regenerated by `make_fixtures.py`) and,
with real data, the user's F9_flowV1 (DISV) and CDF_Mounding (DISU) runs. `test_wells_surfaces.py` (0.2.0) covers the other surfaces (stored settings cleaned, cells traced exactly to the
cell edges, smooth sampling, warnings instead of errors, the elevation range with and without `in_range`, lines,
marks clear of the explorations, legend) and the screens and water levels (`screen_and_levels` rules for
depths and elevations, left-out values, the water-level table and its kinds, dates, the drawing: brackets,
leaders from mid-screen, open and filled triangles with their tips on the levels, labels that never overlap, the
points CSV). `test_panel.py` covers the 0.2.0 panel (all sections closed, segmented controls, round trip of
every new setting, surface rows, header chips).
