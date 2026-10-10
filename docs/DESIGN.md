# XSections design (settings version 7)

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
   **tiled** across sheets with match lines (`tile`, default on). (Since 0.3.5 this is the *Auto* page
   orientation; *Landscape* or *Portrait* uses only that one: decision 25.)
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
   none, is chosen. (Since 0.3.3 the explorations are rows of point layers, decision 22: no row is the
   ground line only, and a ticked row whose layer is gone is the error.)

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
    stands beside the scale bar (compact, or no notes) or under the notes (standard). *(Superseded in part by
    decision 23, 0.3.4: there are no line colours by type any more; the legend is always labelled "Legend:", and
    a Color layer lists the colours of its own QGIS style.)*

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

## Decisions from the user (2026-10-06, version 0.3.1: preview tools)

20. **Preview tools** (`ui/preview.py`, `ui/readout.py`, `core/hover.py`, `MapFeedback.show_cursor`,
    `core/surfaces_csv.py`, `ui/surfaces_csv_dialog.py`), settled over three mockup rounds. None of it is ever
    on an export.
    - **Readout row** above the plot, not a tooltip (the user: a tooltip is distracting and covers things). On
      hover it shows the distance from the start label (or the station, with station labels), the cursor
      elevation, then every line, the ground first, with its elevation and depth: "13.6 bgs" below the ground
      surface, "0.6 ags" above it. The line nearest the cursor is bold and shaded. **Nothing moves while
      hovering**: each value has a fixed slot sized once per layout for the widest text it can show (the user:
      cells resizing as "bgs" turned into "above ground" made the row very hard to read). The row wraps only in
      a narrow dock, at a height fixed per layout. Values are read off the drawn arrays by `core.hover.z_on`
      the way matplotlib draws them: nan past the line's ends and in gaps ("no DEM data"). (The sheet's
      water-table marks keep the 0.3.0 rule, `figure._mark_z`; the two differ only at a vertex just before a gap.)
    - **Explorations:** pointing at one snaps the guide to it, and the row shows its label and type, distance
      and offset, top and its source, total depth and bottom, the screen (elevations, and depths below the
      top) and each water level (measured or ATD, date, depth below the top). The map rings it and draws a
      dashed line to its foot on the section line.
    - **Map marker:** a navy dot with the distance on the section line at the hovered distance (a canvas item,
      `MapFeedback.show_cursor`). **Map to preview:** hovering the map within 2.5 × the tolerance of the line
      (or 15 px; only 15 px on a ground-only section) moves the guide and the row ("On the map: 50 ft right of
      the line"). Points beyond the ends are ignored. A zoomed preview never scrolls by itself; an edge tag
      points to a guide that is out of view. No model cell numbers and no click-to-pin (the user).
    - **Zoom the whole plot** (the user: not matplotlib's rectangle zoom, which only changes what is inside
      the axes). The wheel magnifies the frame, ticks, labels and data around the mouse, from 100 % (the whole
      section in the panel) to 800 %, less on high-DPI screens or wide docks (a pixel budget). The canvas sits
      in a scroll area without scroll bars; a zoom resizes the canvas and raises the figure dpi together, so the
      layout in inches never changes and the text stays sharp. Drag or Shift+wheel pans; double-click fits.
      The matplotlib toolbar is gone (the user); the new one has Fit, Zoom out, the percent, Zoom in, Surfaces
      CSV… and the hover toggle (remembered per user, not per project; two toggles since 0.3.2, decision 21).
    - **Surfaces CSV…** (the preview toolbar only; no points button there, the user): x = distance along the
      section, y = elevation, in feet. *One row per point, as drawn* (`surface, part, distance_ft,
      elevation_ft`; a cell step is two rows; a gap is a row with a blank elevation, then the next part) or
      *One column per surface* (labels in the top row, x in the first column, then one column of y per surface,
      every N ft (10 by default) and at each bend and the end). Map coordinates are optional (`map_x, map_y`,
      off by default). File "Section A-A' surfaces.csv".

## Decisions from the user (2026-10-06/07, version 0.3.2: readout tiles and popup)

21. **The readout row becomes a strip of equal tiles, and the popup comes back as an option** (`ui/readout.py`,
    `ui/popup.py`, `ui/preview.py`). Supersedes the fixed slots of decision 20. *(Superseded in part by decision
    23, 0.3.4, the compact strip: N is 1 + the number of lines, the first tile joining the distance and the
    cursor; the width a tile needs is the widest NUMBER only; one row is about 45 px tall. The popup is
    unchanged.)*
    - **Every tile exactly the same width, always** (the user: "It hurts my eyes otherwise"), for the lines and the
      explorations alike. The strip is a grid of N equal columns, N = the longest row any hover can give for the
      section (2 + the number of lines, or the longest exploration row; 1 + since 0.3.4, decision 23); a shorter
      row leaves its last tiles empty. The width a tile needs is measured once per layout (a new section, a font
      change) from the widest text any tile can show, digits measured as 8 and values in bold (since 0.3.4 the
      widest number only: labels, details and names are cut with "…", decision 23); a width change only
      recomputes the tiles per line (min(N, room / need)) and the height (lines of 58 px; 40 px since 0.3.4).
      Hovering only changes the painted text.
    - **Elegant, like the round-1 popup:** three lines per tile: a small muted label (with the line's swatch, or the
      water-level symbol), the value in semibold tabular figures with a muted "ft", and a muted detail ("13.6 bgs",
      "0.6 ags", "no DEM data", a date and depth, a source). Thin inset dividers; the line nearest the cursor gets a
      soft tint and a bold value. White in every theme (it continues the plot).
    - **Popup next to the cursor** (round-1 look): a small white card painted by hand on the preview's viewport,
      never taking the mouse: the distance and cursor elevation (or the offset from the line for a map hover), a
      table of every line with its elevation and depth, the nearest tinted, and the map X, Y; for an exploration,
      its top, total depth, screen and water levels. Placed beside the cursor and kept inside the preview; by the
      guide for a map hover; hidden off view, while panning and when the mouse leaves.
    - **Two toggles, "Readout row" and "Popup"**, replace the 0.3.1 crosshair. Both start on and both are remembered
      between sessions (per user: `hover_strip`, `hover_popup`; the 0.3.1 `hover_readout` value is not read). The
      guide, dots, axis tags, map marker and map-to-preview hover work while either is on; with both off there is
      no hover. Turning the row off gives the plot its room (one re-layout).
    - A screen reaching above the exploration's top reads "0.4 above – 9.6 below top" (never a negative depth).

## Decisions from the user (2026-10-07, version 0.3.3: several exploration layers and other points, settings version 6)

22. **Several exploration layers, the left-off list, layers out of the elevation range, and other points**
    (`core/model.py`, `core/explorations.py`, `core/others.py`, `core/build.py`; `render/scales.py`,
    `render/figure.py`; `ui/point_guess.py`, `ui/point_rows.py`, `ui/dock.py`; the hover in `core/hover.py`,
    `ui/preview.py`, `ui/readout.py`, `ui/popup.py`, `ui/map_feedback.py`). Settled on an approved mockup
    (version 3, 2026-10-07).
    - **Rows** (the user: "we usually have explorations by others as a separate QGIS layer").
      `Settings.point_layers` is a list of exploration rows in panel order (`model.POINT_LAYER_DEFAULTS`, cleaned
      by `clean_point_layer`): each its own layer, tick (`visible`), legend name (`name`, "" = the layer name),
      `look` and `color` (the picked colour; gone since 0.3.4, decision 23), `in_range`, label and type fields,
      ticked `types`, top / bottom elevation / total depth
      fields, and the screen and water fields (measured level and date, ATD level and date, `wl_values`,
      `screen_values`, a water-level table with its fields and ATD kinds). Shared by every row, as before (the
      user: shared rules stay shared): the tolerance, label direction and text, the top rule and its 25 ft check,
      zero-is-missing, TD labels, screens on or off, the water-level label and the data line colours (gone
      since 0.3.4: each row's Drawn in, decision 23).
    - **One way in.** The 21 flat 0.3.2 keys (`model.FLAT_LAYER_KEYS`, `points_layer_id` … `wl_atd_values`) stay in
      `Settings` as the single-layer shorthand, used only when `point_layers` is empty, through
      `layer_rows(s)`; everything that needs the rows calls it, never `s.point_layers`. Per-row work reads a
      per-row view, `layer_view(s, row)` (a `Settings` with the row's fields in the flat keys), so
      `find_explorations`, `top_and_bottom`, `screen_and_levels`, `read_wl_table` and the hover read a row as they
      read 0.3.2's one layer; `hit_settings(s, hit)` is a hit's view. The panel always writes rows and leaves the
      flat keys at their defaults.
    - **Build.** `build_section` builds every ticked row with one sampler and one ground profile, and stamps each
      hit with its row (`Hit.layer_index`, `layer_id`, `layer_name` = the legend name, `look`, `color`,
      `in_range`); `SectionModel.point_layers` holds one `PointLayerInfo` per row (on, plotted, left off, near,
      beyond). A table shared by two rows is read once. A ticked row whose layer is gone is an error that names
      the row (when more than one is ticked) and the ways out ("… Choose it again, untick its row or remove
      it."): decision 9 still holds, explorations are never quietly dropped; a row without a layer chosen is
      skipped.
    - **Plot everything chosen** (the user: "I want it to plot everything that I choose, even if they are within
      1-foot"): no de-duplication between layers, no row wins. Hits sort by (station, row, label).
    - **Looks** (the user: "Explorations by others should, by default, look no different. But I'd like to be able
      to style them differently, optionally."): Black (default), Gray (`LOOK_GRAY` #8a8a8a) or Colour (default
      #b5651d). Gray and colour change the depth line, its bars, top cap, dotted link and frame arrow, and the
      tick, the name and the TD label (`figure._Painter._look`); the widths stay black's (0.75 pt; 1.6 pt By type).
      Screens and water levels look the same in every layer. *By type* colours the black rows by type
      (`type_styles` and `legend_types` read black hits only). The first row's lines are drawn last, on top; one
      tick call per ink colour, black first. The legend gets one entry per row (`LegendEntry` kind "layer") only
      when the rows with plotted hits are drawn differently from each other; otherwise it is 0.3.2's legend. With
      *By type*, a Black row's entry reads "{name} (lines by type)" and its swatch shows the colours its lines are
      drawn in (up to three, end to end; dark gray only for a line without a type). *(Superseded by decision 23,
      0.3.4: Drawn in is Black | Gray | Color; Color takes each exploration's colour from the layer's own QGIS
      style, with black names, ticks and TD; the picked colour #b5651d, Data lines By type, the type palette and
      the "(lines by type)" entries are gone, and the depth widths are set in Sheet style. Gray, the drawing order
      and the "drawn differently" rule for Black and Gray rows stay.)*
    - **The left-off list** (the user: "there could be a separate list of plotted things that generates from my
      choices in the plugin. I could then manually turn off certain ones"; final answer: left out of the points
      CSV and the map highlights too). `Settings.hidden_points` holds sorted entries "LINEKEY|LAYERID|FID"
      (`line_key(s)` = "layerid#fid" for a line feature, "drawn" for a drawn line; `hidden_key`). Built hits whose
      entry is listed go to `SectionModel.left_off` instead of `hits`, so the sheet, the plan, the points CSV,
      the map rings, the hover and the flags leave them out with no change of their own. Keyed by layer id and
      fid (two rows of one layer share an entry; labels repeat), never pruned: an entry for an exploration that
      is not chosen is inert, and applies again when it is. *Show all* clears the current line's entries; a new
      drawing clears "drawn"; *Reverse* gives the new line exactly the old line's entries; *Save line to layer*
      copies them to the new feature; a layer removed and added again under the same name (a new id, the same
      fids) takes its entries along, a layer of another name never does. That holds for the section-lines layer
      too (the entries of its lines follow it, and a line box left empty goes back to the line in use), and for a
      row's layer that a project reopened while the file was unavailable (moved, offline) kept under its name:
      the row learns the name from the unavailable layer QGIS keeps, so the file added again is taken back with
      every stored key. Shapefile fids renumber when features are deleted (accepted).
    - **Out of the elevation range, and the frame arrow** (the user, final answer: no fixed depth). A row with
      `in_range` off (supply wells to begin with) adds only its tick bases and tops to the automatic range
      (`scales.hit_in_range`, `_data_extent`); its bottoms, screens and levels add nothing, so the frame is set by
      the ground, the surfaces and the in-range rows. A hit of such a row that reaches below the frame
      (`scales.runs_below(h, z_min, s)`: out of range, a depth line, the bottom below `z_min`, the top above it)
      stops exactly at the frame: no bottom bar, a small chevron (`CLIP_GID`, 0.06 × 0.04 in, tip 0.015 in above
      the frame, the line's colour and width) and its TD 0.045 in right of the line on a baseline 0.03 in above
      the frame (always, even with TD labels off: it is the only depth shown; up a row, at most two, on a clash;
      left of the line near the right edge). A level of a row out of the range outside the frame, and a screen
      whose top is below it, are not drawn, whether its line runs below the frame or not (no depth, or Depth
      line off), and the legend and the notes do not list them (`scales.frame_levels`, `frame_screen`; the plan,
      made before the frame is known, counts them all); the Explorations readout says so ("HW-1 runs below the
      frame (TD 254′; water level below the frame)", "SW-1: water level below the frame"); hover, popup and CSV
      keep them. In-range rows under a manual range keep 0.3.2's plain clip. TD labels are laid out by
      `scales.td_page_layout`, which the sheet and the plan's warnings share: (1) the in-range explorations'
      under their bars, as always (`td_labels(..., label_hits=...)`: in-range labels set the range, every hit is
      an obstacle); (2) those of rows out of the range drawn whole; (3) the TDs beside the frame arrows: right of
      the line (left near the right edge), else the other side, else up a row (two at most), clear of every bar,
      arrow and TD label (else the spot covering the least of them); (4) the labels of (2) with no row inside the
      frame: beside the line at its bottom bar, either side, else a row up or down, clear of the same, else left
      out and named in the plan's "No room for the TD label of …". The notes add "An arrow at the bottom of the
      frame: the exploration goes deeper; its TD is beside the arrow." when any hit runs below.
    - **Notes per layer:** each row's tops, bottoms, screens and levels text; identical texts merge, so one layer
      (or several with the same fields) reads exactly as 0.3.2, and different ones name the layers ("Bottoms:
      top minus ExploDepth in A and B; top minus WellCompleteDepth in C.", short form "(A and B); (C)";
      `figure.layer_views`, `depth_sources_text(..., views)`, `screens_sources`; the notes' text lives in the pure
      `render/notes.py`, which figure.py re-exports and the plan reads).
    - **Other points** (the user: "point layers of other features, like springs … plotted at LIDAR elevation or
      some elevation defined in the attribute table"). `Settings.other_points` rows (`model.OTHER_POINT_DEFAULTS`:
      layer, tick, legend name, label field, optional type field and types, `shape`, `color`, `size`, `elev`,
      `elev_field`, `elev_empty`), found by `core/others.find_other_points` with the same "within" distance and
      end caps as the explorations (`explorations._project_points`, shared), in `SectionModel.other_points` and
      `other_layers`.
      - Symbol: asterisk (the default, the user: "an 8-pronged, bold blue asterisk for seeps": #1f6fb2, 7 pt,
        strokes 0.42 × the half size), circle, square, diamond, star or triangle (white-edged), 3 to 20 pt;
        explicit patches and lines in data coordinates, never matplotlib markers; z 4.8 (`POINT_Z`: over the
        ground and the water levels, under the ticks).
      - Elevation `line` (the default; the user: "just slightly off, barely touching the groundline"): the
        lowest ink sits 0.1 pt (`OTHER_REST_GAP_PT`) above the top of the drawn ground stroke, checked under
        every lowest point of the symbol, so a slope never cuts it (`scales.rest_on_line` on the exact ink:
        `symbol_capsules`, `capsule_top`/`capsule_bottom`, `stroke_top`; the ground is read near each sample
        only, and the preview, drawn small, keeps one vertex per r / 8 of paper, so the cost does not grow with
        a dense LIDAR line); in a DEM gap, above the nearest ground. `lidar`: the LIDAR at the point's own x, y; the symbol's centre marks it, with a dotted lead from
        the ground line when the symbol is more than 0.05 in below it; no LIDAR there: the ground line, flagged.
        `field`: an elevation field (ft), kept but flagged when more than the top rule's limit from LIDAR; where
        it is empty (zero too, with zero-is-missing), `elev_empty` decides: the ground line, the LIDAR, or off
        (left out and counted). LIDAR and field points count toward the elevation range.
      - Label: horizontal, the name (or name and offset, with Label text), centred above the symbol and above
        the ground line when the symbol is below it, raised clear of the other labels, the exploration marks,
        the TD labels and every point's symbol, and at least 0.05 in above the ground line's middle under its
        whole width (on a slope the ground under its uphill end is higher: `scales.ground_top_fn`), with a leader
        when raised (from the symbol, or from the ground line over a symbol below it) (`scales.other_label_layout`;
        the plan reserves room with `other_label_top`). A name that exploration leaders run through gets a white
        box (the leaders pass behind it). A point whose centre a manual range cuts off is left out with its label
        (its label would stand outside the frame) and named in the plan's warning, like a tick.
      - Like a surface (decision 15), a point row whose layer is gone is left out with a warning, never an
        error; a missing elevation field is an error naming the row. Listed in the legend (the symbol, at most
        6 pt, after the water levels) and the notes ("Seeps within 150 ft of the section line: on the ground
        line."; "From a field" with no field chosen reads as its "Where it is empty" choice); ringed on the map
        with the explorations; not in the points CSV. The Other points readout lists up to six flags; the others
        are in the message line.
    - **Field guesses** (`ui/point_guess.py`, pure: no widgets): whole names, ignoring case, `_`, `-` and spaces
      (since 0.3.5 every punctuation mark and a trailing unit in parentheses, decision 24), first match wins,
      number fields only for number boxes (since 0.3.5 a number box also takes text fields, number fields first,
      decision 24), and never the layer's primary key (the GeoPackage
      fid `id`; a saved field that is the key is kept). Labels ExploName, AESI_MapLabel, ExploID, Name, MapLabel,
      Label, ID; types ExploType_resolved, ExploType, Type; total depth WellCompleteDepth before ExploDepth;
      measured levels, depth names first (DepthToGW …) then elevation names (WL_Elev … GW_Elev …); the ATD field
      of the same kind as the measured one (GW_Elev_ATD, DepthToGW_ATD …; without a measured field, elevation
      names first); a date only with its level (… ExploDate); "Levels are" from the guessed field's kind. A new
      row is out of the elevation range when its layer's name contains "supply" or it has a WellCompleteDepth
      field. A fresh project gets an exploration row for each point layer named like explorations (layers panel
      order, supply-like layers last and unticked, at most 6; with none, the first point layer not named like
      seeps or springs) and an Other points row for each other layer named like seeps or springs. Guesses are
      never saved by themselves. Changed on purpose: a fresh CDF_wells project now guesses DepthToGW as depths
      dated by ExploDate (0.3.2: GW_Elev as elevations, undated); saved projects keep what they have.
    - **Dates stored as numbers** (`explorations.date_text(value, epoch_ms)`, for number fields): an integral
      value of at least 1e9 in size is milliseconds since 1970 (UTC calendar, never `fromtimestamp`, which fails
      for negatives on Windows), written "M/D/YYYY"; before 1900 (the 1899-12-30 zero date) is blank; smaller
      numbers (YYYYMMDD, a year) are written as they are.
    - **Type values:** "" in `types` is "(no value)", NULL or empty (`IS NULL`, and `= ''` for a text field); a
      list without it gives 0.3.2's filter, `[]` every value, `[NO_TYPES]` none.
    - **Hover** (the user: "Hover over an exploration shows its layer when more than one layer is on; hovering a
      seep shows it"). `core.hover.hover_targets(model)` = the hits, then the other points (one index for the
      preview, the readout, the popup and the map). With more than one exploration row on, the lead tile's small
      print and the popup's first row ("Layer") name the layer. An other point shows its type or layer name,
      distance and offset, its elevation and where it came from (ground line, LIDAR at the point, the field, or
      the fallback), and the LIDAR or the ground line beside it; never the water-level titles. Explorations at
      the same spot (decision 4 plots both: TW-2 and D-447 (TW-2) in his data): the nearest is named (the first
      row wins a tie), its lead tile says "+N here" and the popup lists the others under "Also here" with their
      layer (up to 3, then "+N more"). The map rings the plotted explorations and the other points; left-off
      explorations are not ringed.
    - **Migration v5 -> v6** (`model.migrate_settings`, after the bottom-field step, so version 1 folds too): a
      stored single layer becomes `point_layers[0]` (black, legend name "", ticked, in the range, the same
      fields, types and table) and the flat keys are dropped; stored rows drop them too; no rows and no layer
      leave them as stored (they draw nothing). A v5 type list keeps its meaning (`[]` includes NULL; an explicit
      list has no "" and so excludes it). Old projects look exactly as before: `tests/test_compat_032.py` checks
      five 0.3.2 projects pixel for pixel through three load paths (since 0.3.4 the bytype one against sheets made
      again with the user's approval, decision 23). Opening one and refreshing writes nothing; the first change
      saves version 6 (version 7 since 0.3.4, decision 23). 0.3.2 opening a version 6 project
      sees no explorations (not supported).

## Decisions from the user (2026-10-08, version 0.3.4: compact strip, colours from the QGIS style, depth line widths, grid styling, settings version 7)

23. **A compact readout strip; each exploration's colour from its layer's own QGIS style; depth line widths and
    grid styling in Sheet style** (`ui/readout.py`, `ui/preview.py`, `core/hover.py`; `core/symbology.py`,
    `core/model.py`, `core/build.py`; `render/figure.py`, `render/scales.py`; `ui/dock.py`, `ui/point_rows.py`,
    `ui/widgets.py`). Settled on three approved mockups (the compact strip; exploration colours, round 4; Sheet
    style). Supersedes parts of decisions 18, 21 and 22 (marked there).
    - **Compact strip, always** (the user: "It all needs to fit in one row when the width is as small as 700 px.
      So need to make things smaller."; no full-size mode). For the application's 12 px (9 pt) font: labels, "ft"
      and details 9 px, values 11 px semibold (bold in the tinted nearest tile), each line 1.2 × its font's size
      (`readout.LINE_K`, not the font's own leading); text inset 4 px each side, tile margins 1 px, strip padding
      4 px at the sides and 2 px at the top and bottom, corner radius 4 px, dividers inset 6 px (from the tile
      box), no minimum tile height; the strip's own swatch 10 × 5 px and water-level symbol 11 × 10 px, 3 px
      before the label (`STRIP_SWATCH_W/H`, `STRIP_ICON_W/H`; the popup keeps 18 × 8 and 12 × 11). The sizes
      scale with the font. One row: tiles 38 px tall at a pitch of 40 px, the strip 45 px (Segoe UI 9 pt at
      96 dpi).
    - **One row of equal shares.** The tiles of a line share the room equally (every tile the same width,
      whatever is pointed at; N = 1 + the number of lines, or the longest exploration or point row). A second row
      only when even the numbers do not fit. **Numbers are never cut** (every value, and the first tile's
      distance); a label, a detail, or an exploration's or other point's name that does not fit ends in "…", and
      the popup shows it whole. The name sits in the lead tile's value slot but is not a number: measured, his
      long supply-well names would set the minimum ("Sammamish Plateau Water and Sewer Well #8" needs 250 px, two
      tiles a row at 700 px; 140 of his labels are wider than an 8-tile column), against his first requirement,
      one row at 700 px. A detail that ends with " · off view" or " · +N here" (the endings `preview.py` adds) is
      cut before that ending, which is drawn whole ("right of t… · off view"); when even the ending does not fit,
      only the ending is drawn. `cells()` and `text()` keep the full texts (`elided()` and `painted()` are test
      hooks). Nothing moves or changes width while hovering, as in 0.3.2.
    - **The numbers-only minimum** (`HoverReadout._tile_need`): the widest number any hover of the section can
      give, in bold, plus the insets, measured once per section and font (samples: "—", the two elevations, an
      offset, the line's length as a distance with its digits as 8, and every hit row's tiles from the second
      on). An exploration's screen value ("525.0–510.0 ft") is the widest: 81 px in Segoe UI 9 pt, so a section
      with screens fits 8 tiles a row in a 700 px preview (the readout is 4 px narrower than the preview, its
      layout margins: 696 px, 688 px for the tiles, 86 px each). His CDF model section (where you are, the ground
      and 6 model lines: 8 tiles) is one row; one line more wraps. Sections without screens fit 11 to 14. "700 px"
      is the preview widget's width, stricter than the strip's own.
    - **The first tile joins "From A" and "Cursor"**: label "760 ft from A" ("7+60 from A" with station labels),
      the distance semibold in the navy of the guide (`Tile.strong`), " from A" muted; value the cursor's
      elevation, detail its depth ("12.3 bgs" / "0.6 ags"). From the map: value the offset ("50 ft"), detail
      "right of the line" / "left of the line", ending " · off view" (or "off view" alone) while the guide is
      outside the zoomed view. No cursor: "—". `HoverReadout.show_values(hv, distance, value, detail=None,
      off_view=False)`.
    - **"Ground"** labels the ground tile in the strip; "Ground (<DEM>)" stays in `hover_lines`, the popup and the
      Surfaces CSV headers.
    - **Water levels, in the strip only** (`core.hover.strip_cells`): a level's tile is titled by its date
      ("2/2/2021"), or "Measured" / "ATD" without one, with its symbol; the value its elevation, the detail
      "11.3 below top". Every other cell is as `target_cells` gives it; the lead cell (the name, with the type in
      its small print) is never taken for a level. **The popup is unchanged** (it keeps `target_cells`), and so
      are the toggles, the hover, the map marker and the sync.
    - **Drawn in: Black | Gray | Color** for each exploration row (the user: "The coloring of the depth lines
      belongs in the explorations section. The 'Drawn In' options in the explorations section should be 'black,
      gray, color'. The 'color' option should get its color for each exploration from the QGIS layer styling
      itself, whatever that is, not the plugin."). No colour picker: the row's `color` key and
      `LOOK_COLOR_DEFAULT` are gone (`clean_point_layer` drops a stored `color`). Color is the colour of the
      symbol the layer's own renderer draws that feature with on the map (`core/symbology.py`, read on a clone of
      the renderer, never started on the layer's own, so the map is never touched; checked on QGIS 4.2.1 by
      probes):
      - single symbol, categorized and graduated: the symbol QGIS draws (`symbolForFeature`). The legend item that
        names it is the feature's own (`legendKeysForFeature`) when that item has the drawn colour, else the last
        item of that colour: QGIS draws a NULL or unmatched value with the LAST category whose value is NULL or
        "", while the legend keys name the first;
      - rule-based (and any other renderer with a legend): the last matching legend item, in the legend's order,
        that has a symbol (the one drawn on top; `symbolForFeature` is None for every rule-based feature and
        `symbolsForFeature` wrongly adds the ELSE symbol, so neither is used). A rule switched off in the Layers
        panel matches nothing, and the ELSE rule does not take its features either (QGIS 4.2.1 does not draw
        them): black on the sheet, as they are absent on the map;
      - every scale range of a rule counts (renderer scale 0): the sheet never depends on the map's zoom.
        Categorized and graduated renderers are read at 1:1 (they have no scale ranges; at scale 0 QGIS 4.2.1
        draws their switched-off classes too);
      - point displacement and point cluster renderers are read through the renderer they wrap; a data-defined
        size legend is left out (removed on the clone: its size classes are not symbols of the layer);
      - a symbol's colour (`symbol_color`): the first enabled symbol layer with a usable colour gives it: its fill
        (a data-defined FillColor first) unless that is transparent, near white (every channel at least
        `NEAR_WHITE`, 230) or the inside of an unfilled marker shape (a cross, a line); else its outline (a
        data-defined StrokeColor first; not an outline that is not drawn); else the next layer; none: black. So a
        white or nearly white symbol (a hollow marker) gives its outline colour. Opacity is not drawn;
      - a feature the style draws with no symbol (an unticked category, no matching rule, a value outside every
        range) is drawn as Black (DATA at the black width) and is not in the legend. A style that cannot be read
        draws its row in black with a warning ("Supply wells: its style in QGIS could not be read
        (RuntimeError); its lines are drawn in black."); the section is still built.
      `build_section` reads a Color row's style once, before its hits are stamped (plotted and left-off hits
      alike: `Hit.style_rank`, `Hit.color`; `PointLayerInfo.style`, a `LayerStyle`); Black and Gray rows never
      read the renderer. The 3-row budget (1.5 s) holds with a row in Color. Tests always give a layer drawn in
      Color a fixed renderer: a memory layer's default symbol has a random colour (so does his GeoPackage, which
      has no `layer_styles` table).
    - **What a Color layer draws** (`figure._Painter._look`): the depth line, its bars and top cap (`mew` = the
      line width), the dotted ground link (0.6 pt) and the arrow below the frame in each exploration's colour at
      the Color width; **names, ticks and TD stay black** (its ticks join the black tick call). Gray is as in
      0.3.3 (line, tick, name and TD gray), at the black width.
    - **Legend** (`scales.layer_entries`; z-free, only the hits and the settings, so the plan and every sheet
      agree). A Color row whose explorations are drawn in colour (with a symbol and a depth line on the sheet) is
      always listed, even alone: one entry (`LegendEntry` kind "style") per colour of its style that is drawn,
      named as the layer's legend names it, in the layer legend's order; an identical label and colour once
      across all the Color rows, where it first comes (his own explorations and those by others share one
      categorized style in Cumberland and Tehaleh, and a By type project opens with both rows in Color: their
      shared categories are listed once), the same label in two colours twice (Tehaleh has two "IT" rules:
      everything is keyed by position, never by label). A single-symbol row is listed once, under the row's
      legend name in its symbol's colour (kind "layer"). Black and Gray rows are listed by name only when the
      drawn rows are drawn differently (0.3.3's rule; each Color row with coloured lines counts as a kind of its
      own, and one whose lines all come out black counts as Black). Blank labels: "(no value)" for a NULL or
      empty category, "(other values)" for an ELSE rule or a blank catch-all, a rule's filter expression (cut to
      40 characters with "…"), a range's "lower - upper". A swatch is the item's own colour (as QGIS's legend
      shows it, data-defined colours aside) at the Color width; Black and Gray swatches at the black width (0.3.3
      drew every layer swatch at 1.6 pt). The label is always "Legend:".
    - **The sheet follows the layer's style.** The dock connects `styleChanged` of every exploration row's layer
      (whatever its look, so switching a row to Color needs no new connection; `rendererChanged` always comes
      with it, and unticking a category or rule in the Layers panel, a new renderer or a new opacity emit it). It
      re-reads the style of that layer's rows and rebuilds only when one of them is visible and in Color; nothing
      is saved. A renderer edited in place (from the Python console), which emits nothing, shows at the next
      rebuild or Refresh.
    - **The row editor** (`point_rows.ExplorationRow`, section "ui" below): *Drawn in* Black | Gray | Color;
      under Black and Gray the hint "Black by default, like your own explorations. Gray sets this layer apart;
      Color takes each exploration's color from this layer's style in QGIS."; under Color the style box, which
      shows what is read ("From the layer's style in QGIS: Categorized by ExploType · 13 categories", up to four
      colour chips, "+ 9 more", "Change them in Layer Properties > Symbology; the sheet follows.").
    - **Data lines (Black | By type) leaves Sheet style**, and the plugin's own type palette goes with it
      (`TYPE_COLORS`, `TYPE_DASHES`, `type_styles`, `type_colors`, `legend_types`, `DEPTH_TYPE_LW`, the
      "(lines by type)" entries and "Line colors:").
    - **Depth lines** (Sheet style, new; the user: "those line width defaults are good. But add adjustable
      settings in the 'Sheet Style' section separately for black line width and colored line width for the depth
      lines."): *Black and gray* (`depth_lw_black`, 0.75 pt, 0.25-3) and *Color* (`depth_lw_color`, 1.6 pt,
      0.25-4), in 0.05 pt steps, and Reset (back to 0.75 / 1.6); `model.depth_widths(s)` cleans them. Gray uses
      the black width; the bars, top cap and arrow follow the line; the legend swatches follow too.
    - **Grid: Green | Gray | Custom** (the user: "You should be able to set major and minor gridline color, width,
      and stroke (solid, dash, dotted). The current default is good and you should be able to quickly reset to
      that default. So keep the Green and Gray buttons, and add a Custom button"). `model.GRID_PRESETS`: Green
      (the default; major #5f9a72 0.7 pt, minor #a8c8b2 0.35 pt, solid) and Gray (#6e6e6e / #b4b4b4, the same
      widths); under a preset one muted line shows its colours and widths. Custom: the major and minor colour (no
      opacity), width (0.1-3 pt) and line (Solid | Dashed | Dotted), with "Start from Green · Gray". The first
      Custom starts from the preset in use (`grid_custom_used`, stored with the project, so a reopened project's
      values are never overwritten by that first start), and Green or Gray never touch the custom values: Custom
      comes back with them. `model.grid_spec(s)` gives what the sheet and the preview draw. Dashes are absolute
      lengths on paper (`figure.GRID_DASH_PT`): dashed 4 pt on, 2 pt off; dotted 0.6 pt on, 1.6 pt off with round
      caps (which add the width, so a dotted line of 1.6 pt or more reads solid). matplotlib multiplies a dash
      pattern by the line width (`lines.scale_dashes`, pinned True in `figure.RC`: the bends, match lines,
      surface dashes and ground dots are scaled patterns), so the grid divides its pattern by the width; a
      pattern starts again at each line's start (a tile's own left edge). A solid line builds exactly 0.3.3's
      artist. **Saved with the project only** (answer 1): nothing goes to QgsSettings, a new project starts on
      Green. **The frame stays 0.9 pt black** (answer 2). The preview draws the grid as the sheet does (with its
      `min_gap`, its widths not scaled); the spacing (major every inch, minor every tenth, or Scale & sheet's
      manual grid) is unchanged.
    - **Settings version 7** (`model.migrate_settings`, after the row cleaning). `data_color` is gone: a project
      that stored "By type" opens with its Black rows in Color (Gray and Color rows kept; a v1-v5 flat project
      folds into its row first, so it converts too); "black" or no key: nothing else changes; running it twice
      changes nothing. A 0.3.3 Color row with a picked colour is Color from the layer style (the key dropped).
      Every load runs `model.clean_sheet_style` (an unknown grid choice or line style dropped, a colour that is
      not "#rrggbb" dropped, else lower-cased, widths clamped, `grid_custom_used` a bool), and an absent key takes
      its default (Green, 0.75 / 1.6), so an older project draws as before. Opening and refreshing writes nothing;
      the first change saves version 7. 0.3.3 opening a version 7 project is not supported (its Color rows get
      0.3.3's default colour, a Custom grid falls back to Green). The user: "yes it is fine that other, previous
      projects look different".
    - **The bytype golden, made again once, with the user's approval** (2026-10-08; the one exception to the
      compat_032 rule, decision 22). The explorations layer of `test_compat_032.py` gets a frozen categorized
      renderer (`_type_renderer`: Boring #df9560, Monitoring Well #3fcaa2, Test Pit #80a7ea, CPT #cec063; only
      Color rows read it), and the gated maker `remake_case` (env `XSECTIONS_REMAKE_GOLDEN=bytype`, only for a
      case in `REMADE`, settings version 7 or later) wrote the case again: no plan differences
      (`bytype_plan.json` byte-identical), new `bytype_sheet1.png` and `bytype_sheet2.png`. `bytype.json`,
      `bytype_hits.json` and `bytype_model.json` are never rewritten (the remake checks that they still match: a
      hits golden written from 0.3.4's `Hit` would hold a memory layer's random id). basic, wells, manual and
      ground stay pixel-identical through the three load paths.

## Decisions from the user (2026-10-09, version 0.3.5: Screens are order, numbers stored as text, the row's range box and table label, page orientation, projection direction)

24. **"Screens are" in the order of "Levels are"; numbers stored as text; "In elevation range" beside Total depth;
    "Water levels from a table"** (`ui/point_rows.py`, `ui/widgets.py`, `ui/point_guess.py`, `ui/dock.py`;
    `core/explorations.py`, `core/others.py`, `core/build.py`, `render/notes.py`). Fixes and two requests he made
    on 0.3.4; settings version 7 unchanged.
    - **Screens are: Elevations | Depths** (the user: "Screens Are should be Elevations then Depths, like Levels
      Are."). Only the buttons' order changed: `screen_values` still stores "depth" | "elevation", the default is
      still "depth", the tooltips keep their meaning.
    - **Number boxes take text fields** (the user: "When I choose an existing, loaded table in QGIS for
      WATER-LEVEL TABLE, I can't choose a water level field."). His Cumberland "Boring Summary" is a CSV opened
      by OGR (`ogr`, no geometry), and OGR's CSV driver reads every column as text unless a `.csvt` says
      otherwise, so the numbers-only Water level box listed nothing and would not open. Every number box (the
      table's Water level; a row's Top elevation, Bottom elevation, Total depth, Screen top, Screen bottom,
      Measured level, ATD level; an Other points row's Elevation field) lists number and text fields
      (`widgets.NUMBER_BOX_FILTERS` = Numeric | String; the box's own icons tell them apart; dates and other
      kinds stay out). Guesses still prefer number fields (`point_guess.pick_field`): a name that matches a
      number field wins; a text field is guessed only when no number field matches **and its values are
      numbers** (`text_ok`: `point_rows.number_texts` reads, only for a text field a guess would take, its first
      50 values that are not empty in its first 2,000 rows, and one plain number is enough); and the fallback of
      a box that needs a field is a number field only. So his typed layers guess as before: their text columns
      hold texts (CDF_wells' String field Elevation_ holds survey sources, "L Green R 2017", "Survey, NAVD 88",
      and is not guessed as an Other points elevation, as in 0.3.4), while a mixed delimited-text layer ("Detect
      field types" on: GS Elev a number, "GW Elev. (ft)" text because of an "NA") still gets "GW Elev. (ft)" as
      the table's level, never GS Elev by the fallback. A field carried over to a newly chosen layer or table
      that is only a text field there gives way to a number field the guesses match (`pick_field(fresh=True)`);
      a saved text field is kept, whatever its values. A box that needs a field and gets none (the table's
      Water level on an all-text table whose level column matches no name, "SWL (ft)", "Reading") shows none:
      `widgets.set_field` clears it instead of leaving the first field QgsFieldComboBox selects by itself (the
      name column), and the build asks him to choose ("Choose the name and level fields of the table of water
      levels …"). Names ignore every punctuation mark and a trailing unit in parentheses ("(ft)", "(m)", "(ft
      bgs)"; not "(ATD)"): "GW Elev. (ft)" is GW_Elev, now in the table's elevation names, with WL_Elevation,
      GW_Elevation, WaterLevel and WL after the others ("Water Level (ft)"); with Levels are = Depths the
      table's depth names come first (DTW …). Also BOH_Elev (bottom elevation) and Depth_BOH (total depth), his
      column names.
    - **Reading** (`explorations.to_number`, `text_number`): a text is a number when, trimmed, it is a plain
      number ("642.3", " 642 ", "-12.5", "1e3") or one with US thousands separators ("1,234.5"); anything else
      ("NA", "dry", "642.3 ft", "1.234,5", "1_000", "nan") is not a number: left out as NULL is. An empty text
      (a CSV's empty cell) is no value, as NULL, and is not counted. Zero-is-missing and every other rule are
      unchanged.
    - **Flags**: the table of water levels gets one model warning per table field (the whole table counted, once
      even when several rows read it: `explorations.WlTable.warning`), "Boring Summary: 3 water levels in GW
      Elev. (ft) are not numbers (left out)."; an exploration's own text fields a flag per hit, 'GS Elev “NA” is
      not a number: left out' (`not_number_flag`, the text cut at 24 characters); an other point whose
      elevation text is not a number is placed as for an empty field and flagged 'Elev “dry” is not a number: on
      the ground line' (or "LIDAR at the point"); with "Where it is empty: Off" it is left out as before.
    - The rest of the table setup is unchanged (Exploration name matched to the row's label field, case and
      spaces ignored; no Kind column = every row ATD; Date any type).
    - **"In elevation range" beside Total depth** (the user: "It is confusing since it is placed below the
      WATER-LEVEL TABLE. … it should be moved next to the Total Depth drop down."). In *More: depths, water and
      range* the checkbox (`in_range_box`, "In elevation range", fits half the editor at the 340 px panel; a
      `point_rows.FitCheckBox` that reads "In range" only while the panel is narrower, 260 px) is the
      right half of the Total depth pair (`depth_pair`, bottoms aligned), its tooltip the full meaning: "Include
      this layer's explorations in the automatic elevation range. Unticked, deeper ones stop at the frame with
      an arrow and their TD."; the hint "Deeper ones stop at the frame with an arrow and their TD." (unticked
      only) follows that pair. The key `in_range`, its defaults and the supply-well guess are unchanged.
    - **"Water levels from a table (CSV, Excel…)"** (the user: "At first I thought it was specifically referring
      to the physical water level table … make the title clearly imply an excel/csv style table."). The row's
      table box is labelled so (upper case, the whole editor width), tooltip "A spreadsheet-style table (CSV,
      Excel sheet, or any layer; no geometry needed) with one row per water-level reading: the exploration's
      name, the level, and optionally its date and kind (measured or ATD)."; the empty choice reads "(none)".
      Every other text says "table of water levels": the errors ("The table of water levels (Boring Summary) is
      no longer in the project. Choose it again, or none." with the name while QGIS still holds the layer;
      "Choose the name and level fields of the table of water levels Boring Summary."; "The level field “X” of
      the table of water levels is not in Boring Summary. Choose another field."), the notes ("a table of water
      levels"), the Screens & water hints and the Levels are tooltip. Code names and settings keys
      (`wl_table_*`) stay.

25. **Page orientation: Auto | Landscape | Portrait** (`core/model.py`, `render/scales.py`, `ui/dock.py`; the
    user: "I'd like to be able to control the orientation of the paper pages - i.e. portrait vs. landscape. Right
    now it is chosen automatically. In the Scale & Sheet section, i'd like to have a way to select Auto,
    Landscape, or Portrait for page orientation. Auto would work like it does now."). Settings version 7
    unchanged.
    - `Settings.orientation` (right after `sheet`): "auto" (the default) | "landscape" | "portrait"
      (`model.ORIENTATIONS`). A stored value is cleaned where the sheet-style keys are (`clean_sheet_style`, run by
      `migrate_settings` for every version: `clean_orientation`, case and spaces ignored, anything else "auto").
      No version step: settings saved before 0.3.5 have no key and get Auto, the search they were planned with.
    - `plan()` (`scales.page_turns`): **Auto** is the search of every earlier version: each candidate sheet (the
      named one, or the allowed ones smallest first) landscape, then portrait; a section too long for one sheet
      tiles on the largest allowed (or the named) sheet, landscape, then portrait. **Landscape** and **Portrait**
      try only that orientation, for one sheet and for tiling alike (with Portrait a long section tiles on portrait
      sheets). The margins, the block under the plot and the fill estimate are worked out as for Auto (every
      candidate sheet in both orientations), so a page gets exactly the same layout whichever setting chose it;
      fill with grid, the notes, the tiling windows and the match lines work as before for the page it gets. A
      custom page is sized to the drawing and ignores the orientation.
    - Messages: Auto's are unchanged, word for word. With Landscape or Portrait they name it: "… larger than
      Letter or Tabloid in portrait. Choose Auto or Landscape, a custom page size, a larger sheet, a smaller scale
      (more ft per inch), or turn on tiling."; the tiling height message gives only that orientation's room ("…
      but a Letter sheet has room for 5.00 in (landscape). Choose Auto or Portrait, a smaller vertical scale …");
      the coarse grid one says "… too coarse to tile on Tabloid sheets in portrait.". "Auto or (the other one)" is
      offered only when the other orientation would hold the section (on one sheet, or tiled with tiling on),
      that is when Auto would give sheets.
    - Panel: under Scale & sheet, a full-width row right under Sheet | Format, **Orientation** Auto | Landscape |
      Portrait (tooltips "As fits best: landscape first, then portrait (as before)", "Every sheet landscape",
      "Every sheet portrait"). Disabled while the sheet is Custom, its buttons' tooltip then "Not used with a
      custom page size: a custom page is sized to the drawing" (the choice is kept for when he leaves Custom).
      Saved and restored with the project; a change saves and rebuilds through the panel's debounce like the
      other sheet keys. The export readout and the chip name the sheet as before ("Sheet: Letter 8.5 × 11 in,
      portrait"; "1,000′ / 50′ · Letter").

26. **The direction on a label is the direction of projection** (`core/explorations.py`, `core/others.py`,
    `render/notes.py`, `ui/dock.py`; the user: "the projections directions are flipped. The projection should be in
    reference to the exploration. So if an exploration is north of the cross section line it is projected SOUTH
    onto the section line."). Settings version 7 unchanged.
    - `Hit.direction` and `OtherPoint.direction` are the 8-point compass direction of (foot − point), from the
      exploration (or other point) onto the line: a well 40 ft north of an east-west line reads "S" ("MW-3 · 40 ft
      S" with Label text "Name + offset and direction"), east of a north-south line "W", north-east of a line
      running north-west to south-east "SW". Before 0.3.5 (0.3.4 and every earlier version) it was
      (point − foot), from the line to the exploration (the reverse). On the line (offset ≤ 1e-6 ft) it stays
      "". Station, offset, side ("L" | "R": where the exploration lies, looking from A to A′) and every geometry
      are unchanged; the left / right texts of the hover and the popup ("192.4 ft right", "right of the line") say
      where it lies and are unchanged, as are the end letters' compass directions (the line's).
    - Texts: the notes "Labels give the distance and direction each exploration was projected onto the section
      line." (compact: "Labels: distance and direction projected onto the line"); the Label text tooltip
      'Name + offset: "MW-3 · 40 ft S" = projected 40 ft south onto the line'. The points CSV keeps its column
      name `direction` (his spreadsheets may use it); its values follow the new meaning.
    - **The manual golden, made again once, with the user's approval** (he asked for the change, 2026-10-09; the
      second exception to the compat_032 rule after decision 23's bytype). Only `manual` draws the directions
      (Label text with offsets), so only it was made again, through the gated maker (`remake_case`, env
      `XSECTIONS_REMAKE_GOLDEN=manual`, `REMADE`): new `manual_sheet1.png` and `manual_sheet2.png` (the labels'
      directions and the notes sentence), and in `manual_hits.json` only the six direction values (`NEW_DIRECTIONS`:
      every other value is the golden's own, checked unchanged); no plan difference (`manual_plan.json` not
      written), model unchanged. The hits goldens of basic, wells and bytype also hold a direction (0.3.2's; not
      drawn): they are not rewritten but compared reversed (`test_compat_032.OPPOSITE`, `_hits_golden`). Every
      other golden is byte-identical; basic, wells, bytype and ground stay pixel-identical through the three load
      paths.

## Decisions from the user (2026-10-09/10, version 0.3.6: hydrogeologic symbols, Other features, the panel redesign)

27. **A hydrogeologic symbol catalogue; Other features: line and polygon layers; the panel redesigned** (new
    `render/symbols.py`, `ui/symbol_icons.py`, `ui/problems.py`; `core/model.py`, `core/others.py`, `core/build.py`,
    `core/hover.py`, `render/scales.py`, `render/figure.py`, `render/notes.py`; `ui/widgets.py`, `ui/point_rows.py`,
    `ui/point_guess.py`, `ui/dock.py`, `ui/settings_store.py`; `scripts/run_tests_parallel.py`). His answers of
    2026-10-09 on two approved mockups (the symbol drop-down; lines and polygons on the sheet), and the panel mockup
    he approved on 2026-10-10 after three rounds (sixteen decisions, D1-D16, and one amendment to the catalogue),
    answering his concern that the panel was getting too complicated (the user: "clean, well-organized ... tight and
    elegant. Not too many words ... a verbose option to turn off extraneous words, like the warnings"). Settings
    version 7 unchanged: only new row keys, with defaults. Supersedes the panel layout of decisions 17, 22 and 24 and
    0.3.3's shape buttons (the "ui" section below follows it).
    - **The catalogue** (`render/symbols.py`, pure: `math` and `typing` only, so core, render and ui all import it;
      0.3.5's symbol geometry moved here from `scales.py` unchanged and is imported back): 30 choices in five groups,
      in the drop-down's order, each a `Symbol(key, name, group, color, rests, mirrors, legacy)`: *Water at the
      surface* (spring, thermal or mineral spring, stream or creek crossing, pond, wetland), *Wells shown as points
      (no log)* (13: use not known, domestic, public supply, irrigation, industrial, monitoring or piezometer,
      observation, pumping or extraction, flowing artesian, drywell or injection (UIC), unused, decommissioned,
      infiltration gallery), *Measurements and samples* (stream or lake gauge, staff gauge, water-quality site, soil
      or rock sample), *Geology and survey* (bedrock outcrop, landslide head scarp, survey benchmark) and *General
      shapes* (Asterisk, Circle, Square, Diamond, Triangle). Drawn after FGDC-STD-013-2006, the USGS topographic map
      symbols and common practice (the module docstring names the sections). Each has its usual colour, a new row's
      colour (the row's colour stays his): `BLUE` #1f6fb2 (water, gauges, the general shapes), `BLACK` #111111 (wells,
      the benchmark), `RED` #c62828 (pumping, the scarp, a sample), `GREEN` #2e7d32 (water quality), `GRAY` #555555
      (outcrop). **The asterisk** (his amendment of 2026-10-10: "move the asterisk down with the other general
      shapes") heads *General shapes*, named "Asterisk"; its key, colour and drawing are unchanged and it stays the
      default of a new point row. Well symbols are for wells **without a log**: wells with depths stay explorations,
      nothing converts.
    - **Old and unknown keys**: the five generic shapes, the asterisk and the star (`LEGACY_DRAWN`) draw with 0.3.5's
      own code, pixel-identical. The star is a legacy key (`LEGACY_KEYS`): kept on old rows and drawn, never offered
      (the drop-down lists it, under "Kept from an older version", only while the row holds it). An unknown key is
      cleaned on load to its kind's `model.DEFAULT_SHAPE` (point and polygon rows the asterisk, line rows the stream
      crossing); at draw time (a hand-made object) `symbols.resolve()` gives `FALLBACK_KEY`, the circle: one explicit,
      tested fallback (0.3.5 drew anything unknown silently as the asterisk).
    - **Geometry** (`glyph(key, size_pt, k, flip)`: primitives `Stroke`, `Ring` (white inside), `Dot`, `Fill`,
      `Letter` in paper inches about the symbol's origin, the point that marks a LIDAR or field elevation; strokes at
      least `MIN_STROKE_PT` 0.6 pt with round caps and joins; waves of 12 segments; the pond's fill its colour at 20 %
      on white, `tint`): the footprint is the exact ink as capsules (`glyph_capsules`, `glyph_bbox`), so resting on
      the ground line, the label obstacles and the hover boxes stay exact. On the ground line every symbol rests on
      its lowest ink but the **benchmark**, centred on it (`rests=False`: its centre marks the elevation). **The
      spring's tail points downhill** (`scales.symbol_flip`, at sheet scale, so every sheet, tile and the preview
      agree): it compares the ground a tail's reach ((0.3 + 1.0) × size) either side of the station and goes to the
      lower side; on flat ground (within `SPRING_FLAT_IN` 0.005 in of paper), in the legend and in the icons it goes
      right, toward A′. The thermal spring's "T" (never under 4 pt) sits opposite the tail. In the legend a new key is
      centred on its ink box (gid `LEGEND_SYMBOL_GID`); every one fits the asterisk's 6 pt reservation, so the legend
      rows and `standard_block_depth` are unchanged.
    - **Icons** (`ui/symbol_icons.py`, theme-independent: only the given colour, white insides and edges):
      `symbol_pixmap` / `symbol_icon(key, color=None, width=22, height=16, background=None)` paint the same
      primitives (11 px nominal in a 16 px icon, `ICON_S_RATIO`, shrunk only to fit; a resting symbol 2 px above the
      bottom, the benchmark centred; `symbol_icon` holds 1x and 2x pixmaps); `bracket_pixmap` / `bracket_icon(color,
      style)` paint a polygon row's mark (solid ticks, the line solid or dashed 4/2 px).
    - **Other features** (D7: the section renamed from Other points; `Settings.other_points` keeps its name and his
      rows): a row's layer is a point, line or polygon layer (`others.feature_kind`, `others.feature_layer`;
      `model.feature_row(kind, **kw)` makes a new row). Row keys after `elev_empty`: `kind` (`FEATURE_KINDS`, the
      layer's geometry as last seen; the build trusts the layer's own), `bracket` ("inside" | "above",
      `AREA_PLACES`), `bracket_style` ("solid" | "dash"), `edges` ("off" | "ground" | "full"). A new line row draws
      the stream crossing in water blue, a polygon row is #7a4fb0 (`AREA_COLOR_DEFAULT`). A 0.3.5 row loads as itself
      plus the four defaults (a point row, drawn as before); 0.3.5 opening a 0.3.6 project leaves line and polygon
      rows out with its "no longer in the project" warning and reads a new symbol as the asterisk (not supported). A
      layer of no geometry kind (a table) is left out: "Other points “X”: not a point, line or polygon layer; left
      out." (the core's warnings keep the "Other points" prefix; the panel shows them as row problems).
    - **Lines: a symbol where the section line crosses** (`others.find_crossings`; no Within distance): one
      `OtherPoint` of kind "crossing" per crossing (a line that crosses twice gives two; a touch and the line's ends
      count), its station exact, offset 0, side and direction "", with the point rows' symbol, colour, size, label,
      type filter and elevation (`others._place`, shared with points). A stretch shared with the section line is one
      crossing at its middle, flagged `ALONG_FLAG` ("runs along the section line for 300 ft"; shorter than
      `ALONG_MIN_FT` 1 ft it is a plain crossing); one stream split into two features at the line is one crossing
      (`_one_per_crossing`: the same label within `ALONG_TOL_FT`). Crossings join `model.other_points` and behave as
      other points everywhere: resting, labels (the name only, never an offset), the elevation range, the legend (the
      row's symbol), the notes (" Creeks where they cross the section line: on the ground line."), the hover and the
      popup (small print "crossing", `hover._offset_cell`), the map rings. Not in the points CSV.
    - **Polygons: a bracket per piece** (`others.find_area_pieces` -> `model.other_areas`, `AreaPiece(fid, label,
      type_value, start, end, open_start, open_end, layer_index, ...)` sorted by start; a polygon that is not valid is
      made valid, touching stretches merge, slivers under `MIN_PIECE_FT` 0.01 ft go): a horizontal line (`AREA_LW`
      1 pt, solid or dashed 4/2 pt) with end ticks 0.06 in down over the piece's stations and its label (the label
      field, else the row's legend name) centred above it in the row's colour, with a halo. A piece that runs past A
      or A′ (that end strictly inside the polygon: more than 1e-3 ft from its edge, in any CRS) ends in an open arrow
      and reads " (continues)" (`CONTINUES`). **In the frame** (the default): above the ground stroke and the
      exploration ticks and labels and the other points in its span, 0.05 in clear (`AREA_CLEAR_IN`); **Above the
      frame**: rows of `AREA_ROW_IN` (0.2218 in) over the frame top. Overlapping brackets stack, each place on its
      own, the longer always above (`scales.area_layout`; footprints include the labels, so labels never collide).
      **Edge lines** (off by default): dashed 0.6 pt (3/2 pt) at each closed end, down to the ground (for a row above
      the frame: to the frame bottom at most) or the full frame height, under the data lines, broken where they pass
      another bracket's label (`figure._edge_runs`). A tiled sheet cuts a bracket at its edge (no tick there) and
      labels its own part. The legend gets a short bracket per polygon row, in its colour and line style (ticks
      solid). Pieces have no hover, no map highlight and no notes sentence.
    - **The plan** (`scales.area_layout`, pure, called by the plan and every painter, so they agree): Auto elevations
      give the inside brackets room as they give the labels (`area_top` in `z_limits`); brackets above the frame grow
      the top margin (`area_band_in` -> `Plan.above_in`, passed to every `margins()` call of the sheet, orientation
      and tiling search) and lift the end letters, BEND labels and titles by it. **A manual range with no room**:
      each cluster of overlapping brackets moves down whole under the frame top, stacking kept, and one plan warning
      names them ("Brackets of {names} lowered: no room under the manual maximum of {z} ft. Raise it to {need} ft or
      set Elevations to Auto."); where the minimum cuts off a bracket's ground it stands on the frame bottom, never
      lost. **The preview lays the brackets out at its own scale** (`scales.AreaFrame` from `figure._Painter`: its
      own tick, label and point boxes, labels at its k), so they keep clear of its relatively larger labels, and its
      band above the frame grows when it needs more rows (never below the sheet's; at most 3 refits); sheets keep the
      sheet-scale layout. A model without line or polygon rows plans and draws exactly as 0.3.5 (a new value is added
      only when it is > 0): the goldens are untouched.
    - **Six sections** (D1; `dock.sections`, object names unchanged): Line, Surfaces, Explorations, Other features,
      Scale & sheet, Sheet style. Depths and Screens & water are subsections of Explorations (`grp_depth`,
      `grp_screens`). Several may be open at once (no accordion); all are closed when the panel opens or a project is
      loaded, as before. **Three levels you can tell apart** (D2): a closed section is a solid tile, an open one the
      navy bar (`SectionHeader`, 30 px); a subsection heading is navy capitals after a 6 px square, with a hairline
      rule, never filled ("a fill means click me": `SubsectionHeading`, 16 px); field names are plain sentence case,
      small and muted (`field_label`). **An open section is one card** (D3, `SectionBody`): the bar over a body framed
      in navy on a 4 px rail (`RAIL_W`), and a 10 px gap before the next tile. The contents, in the mockup's order
      (every attribute name kept, section 4.2 of the build spec):
      - Line: Layer | Feature; Pick, Draw, Selected; Ends A to A′, Reverse, Save to layer.
      - Surfaces: the Ground card, the surface cards, + Surface, + Bands… and + MODFLOW 6… on one row, the Units &
        datum pill.
      - Explorations › Layers (the rows, + Add layer; "top drawn first" beside the heading with Verbose), All layers
        (Within | Labels, Label text), Depths (Depth line, TD label, Tops from, the Checks pill: 0 means missing,
        Ignore a table top off LIDAR by over [25] ft), Water & screens (Draw them, Print beside Off | Elev. | + date),
        Plotted (the list, Show all in its heading).
      - Other features › Layers (the rows, + Add layer).
      - Scale & sheet › Scale (Horizontal | Vertical), Elevations (Auto | Manual and Split across sheets; Lowest |
        Highest shown only under Manual, out of "More"), Sheet (Size | Format, Orientation, Title, the Distances &
        printers pill).
      - Sheet style › Grid (Look Green | Gray | Custom with its legend line and the custom table; Spacing from the
        scale (1 in, 0.1 in) and, unticked, the horizontal and vertical major / minor spacing, moved here from Scale &
        sheet; Fill sheet | Below lowest), Depth lines (Black & gray | Color, Reset in the heading), Page (Printer
        edge; Compact layout, Notes, Bend lines, Shade below ground). The NEW tag and the dashed rule are gone.
    - **Layer rows are cards; an open one joins its section ("Flare")** (D4, D5; `widgets.LayerCard`): a closed row
      is a small card (1 px `field_line` border, `row_rail` on hover, radius 4 px); a click anywhere on it but its
      check box, colour button, badge and ⋯ opens its editor. Open, the row and its editor are one light band
      (`row_open`) reaching the section's rail: the rail beside it turns light blue (`row_rail`) and fades back to navy
      over 8 px above and below; the band's top and bottom curve into the rail with concave swoops of radius 8 px
      (`SWOOP`), its right corners round 6 px; a 1 px outline (`band_line`: #8fb6ca light, #3f6a80 dark; he asked for
      it on 2026-10-10) runs along its top, right and bottom edges round both swoops (`paint_flare`, painted by the
      `SectionBody` for each card it watches). Spacing as the mockup's: 12 px above an open band and between two open
      bands (their swoops overlap), nothing extra under the last (`link_cards`: `set_first`, `set_last`,
      `set_after_open`); nothing moves sideways when a row opens. Surfaces: the Ground card (`dock.GroundRow`: no
      check box and no ⋯, a black bar, its "always drawn" tooltip on the name) and the surface cards (`SurfaceRow` is
      a LayerCard; `ModelSurfaceRow` unchanged).
    - **Exploration rows have tabs Layer | Depths | Water** (D4; `widgets.RowTabs`, 24 px; the mockup's grouping
      exactly): Layer (Layer; Legend | Drawn in; the style box under Color; Label | Type; Types), Depths (Top
      elevation | Bottom elevation; Total depth | In elevation range), Water (Measured level | Date; ATD level | Date;
      Screen top | Screen bottom; Levels are | Screens are; Water levels from a table (CSV, Excel…) and its table
      box). The Water tab is dimmed (still clickable; tooltip "No water-level or screen fields") when the layer has
      none. "More: depths, water and range" is gone. Subtitles lose the layer name and the counts ("ExploName · 2 of
      4 types · black", the label field in a darker ink; "layer not in the project · color"; "no layer chosen").
    - **Other features rows** (D7; `OtherPointsRow`, one class for the three kinds, its kind from the layer, else the
      stored `kind`): each with its kind's icon (the symbol, or the bracket mark) and subtitle ("points · Name ·
      ground line", "lines · Name · 2 crossings", "areas · Name · bracket in the frame"). Points and lines: Layer,
      Legend | Label, Type and Types (kept for every kind: the core filters any), Symbol | Color | Size, Elevation
      Ground line | LIDAR | Field (a line row Ground line | Field, LIDAR shown only when stored) with Field | Where
      empty. Polygons: Layer, Legend | Label, Type, Bracket In the frame | Above the frame, Edge lines Off | To ground |
      Full height, Color | Line Solid | Dashed. **The symbol drop-down** (`point_rows.SymbolCombo`, replacing the six
      shape buttons): the catalogue's groups as headers that are never picked or current (keyboard, wheel, a click on
      one), each symbol with its icon, its name and the mockup's description as its tooltip (`SYMBOL_TIPS`); the
      closed box shows the row's colour. **Choosing a symbol sets its usual color** (always; he can change it after).
      Picking a layer of another kind switches an untouched default symbol and colour to the new kind's. + Add layer
      takes a free point, line or polygon layer (`dock._default_feature_layer`: named like seeps or springs first).
    - **Shorter names; each removed explanation in the tooltip of its control** (D12): Layer, Ends, Save to layer,
      + Surface, + Bands…, + MODFLOW 6…, + Add layer, Legend, Label, Type, Types, Depth line, TD label, Tops from, 0
      means missing, Draw them, Print beside, Lowest, Highest, Size, Look, Fill sheet, Below lowest, Black & gray.
      Set-once settings fold under round pills (Units & datum, Checks, Distances & printers) that open a dashed box
      (D6, `widgets.Disclosure`).
    - **Verbose** (D13): a checkable last item of the ⋯ menu ("Verbose", tooltip "Hints and notes under the
      controls"), off by default, stored per user in QgsSettings `xsections/verbose` (`widgets.verbose`,
      `set_verbose`, `verbose_hub().changed`, through `settings_store.user_value`), never in the project. Off: no
      explanatory sentence under any control. On: the hints come back under their controls (`widgets.Hint`: shown
      exactly when its owner wants it and Verbose is on) and so do the readouts (`widgets.Readout`, now Verbose
      notes: length, coverage, sources, Plotted counts, VE, the sheet ...). Two 0.3.5 hints go entirely (they pointed
      from sections that are gone). Problem lines, badges, chips and the status line do not change with Verbose.
    - **Problems, guesses and notes** (D14; `ui/problems.py`, pure, run by `dock._update_problems` after every build):
      a **real problem** (something left off the sheet or changed on it) shows ONE short amber line in its row
      whatever Verbose is ("3 water levels are not numbers; left out", "B-4: DTW “dry” is not a number: left out (+2
      more)", "Layer not in the project", "4 left out: no Elev_ft", "Style not read; drawn in black"; on the Ground
      card the DEM gaps, on a surface card its warning) with an amber badge counting it, and the section header gets
      an amber count chip ("2 layers need a look"; hidden while its main chip is already amber). A **guess** (fields
      guessed from their names) shows only the amber "check" badge. **Notes** (past the ends, below the frame, the
      readouts' facts) are Verbose only. The core's warnings are matched to their rows by their text; what no row
      owns (units assumed, the plan's warnings, errors) is the status line's.
    - **The check card** (D15; `widgets.CheckBadge`, `CheckCard`, `CardHost`: one card per panel, a child overlay,
      272 px): it opens ONLY on a click on the badge, never on hover; it closes on a second click, 100 ms
      (`CARD_CLOSE_MS`) after the pointer has left badge and card, on a button, a scroll, a section opening or
      closing, and when the panel hides. The mockup's look: an amber top edge, a round amber icon, the bold title, a
      source line (layer · where it came from), a field → value list in monospace (up to `CARD_ITEMS` 8, then "… and N
      more"), an optional note ("Only plain numbers are read; 1,234.5 is fine."), and its buttons: Open Layer, Open
      Depths or Open Water open the row on that tab; Looks right (the primary one) confirms a guess.
    - **`guessed` and Looks right** (D15): the exploration rows' new last key `guessed` (members of `model.GUESS_KEYS`,
      the eleven field keys a guess fills, once each, in that order) lists the boxes guessed from their names that he
      has not checked: a fresh guess's; on load the stored list, but for boxes now empty, plus boxes guessed again (a
      saved field the layer lacks). His own choice in a box (or of Levels are, for the level boxes) drops it; **Looks
      right clears them for good**, saved in the project with the row. The card "Fields were guessed" lists each box
      and its field (Measured level → DTW · depths); the old sentence ("Guessed from the field names (check them):
      …", `point_guess.guess_hint`) is a warn hint above the tabs, Verbose only. A 0.3.5 row loads with none (no
      badge); opening a project still writes nothing until his first change; 0.3.5 drops the key. Other features rows
      get no guess badge.
    - **The status line** (under the panel's scroll area, above Refresh, ⋯ and Export…): a dot (green ready, amber
      warning, red error) and the message (`problems.status_warnings`: the plan's warnings and every model warning no
      row covers, amber; errors red, as before), or "Ready · 12 explorations, 3 points, 2 crossings, 1 area"
      (`problems.ready_text`; "Ready · ground line only"). The DEM units warning's "Surfaces > More: units and datum"
      reads "Surfaces › Units & datum" there (`OLD_PLACES`; the core's text is unchanged).
    - **Light and dark** (D16; `widgets.theme_for`): the mockup's light and dark tokens. The dark ones are fixed
      colours (bar #2f5a6f, tile #233038, band #1c3341 ...), no longer the palette's highlight (Night Mapping's
      orange); ink, field and disabled colours still come from the palette, and the panel's own background stays the
      palette's Window (#323232 in Night Mapping). Sizes are the mockup's px at Segoe UI 9 pt (12 px), fonts scaled
      from the application font; the mockup's weight 500 is drawn DemiBold, as Edge shows Segoe UI (`MEDIUM`).
    - **Narrow panels** (260 px with Segoe UI 9): nothing is cut. Two fields side by side (`pair` -> `widgets._Pair`)
      stack while a column is narrower than what it holds; the Page check boxes go to one column (`checkbox_grid` ->
      `_CheckGrid`); the Ends row and the three add-surface buttons put their last part on a second line
      (`dock._FitRow`); "Split across sheets" reads "Split sheets" (`FitCheckBox`). At 340 px the mockup's layout
      holds unchanged. Dashed boxes are painted (`paint_dashed_box`, 3 px dashes, 2 px gaps: Qt's stylesheet draws a
      dashed border as dots), and a Hint's link to the Verbose hub is a Qt slot, dropped when the hint is deleted.
    - **The test runner's deadline** (`scripts/run_tests_parallel.py`; "Tests" below): a worker that exits without
      unittest's result while a process it started holds its output counts as crashed after `RESULT_GRACE`; any
      worker, and the serial re-run, still running at max(900 s, 4 × its planned time) × its time factor is killed and
      fails the run (`timed out workers=k`).
    - **Compat**: the goldens (`test_compat_032`) are untouched and pass. Point rows draw pixel-identically to 0.3.5
      (before / after renders of the six old shapes with explorations, sheets and previews, standard and compact, 100
      and 300 dpi: identical). No settings version step; opening a project writes nothing.

## Real data the user works with (copies for tests, never touch originals)

`<scratch>/realdata/CDF_wells.shp`: 8 wells, **EPSG:4326 PointZ** (must be transformed), fields
`ExploName` (label), `ExploType` (values like "MW, EB-1W, TW, OBW"), `ExploDepth` (ft),
`ExploElev` (collar, sometimes 0 or wrong), `DepthToGW`, `GW_Elev`.
`<scratch>/realdata/cdf_lidar.tif`: 2667 x 3127, 1 ft cells, US survey feet, Float64,
no nodata value, elevations 527-700 ft, WA State Plane South (custom WKT, no EPSG code).
His `Explorations.gpkg` (17.9 MB; path in `tests/fixtures.GPKG`, or env `XSECTIONS_GPKG`; **read only**: tests
byte-copy it with `shutil.copy2` and open the copy, sqlite3 only read-only on the copy), all EPSG:4326 points with
a GeoPackage fid `id`: `Explor_AESI_pt` (32,635: ExploName, ExploType_resolved with 12 types, ExploElev, ExploDepth,
DepthToGW measured depths, GW_Elev, ExploDate as epoch-millisecond integers), `Explor_Other_pt` (4,722, the same
names, no water fields) and `Well_Supply_pt` (1,128: AESI_MapLabel, ExploType_resolved with 418 empty and 16
"SPRING WELL , GRP A/B/DOM", WellStatus, ExploElev, ExploDepth, WellCompleteDepth up to 1,035 ft, GW_Elev_ATD with
zeros, DepthToGW_ATD, ExploDate as a DATETIME). Springs in the supply layer are wells at a spring zone (the user):
drawn as supply wells. The GeoPackage has no `layer_styles` table: the layers are styled in his QGIS projects
(0.3.4, decision 23). Cumberland.qgz: `Explor_AESI_pt` categorized by ExploType (13 categories, the NULL one
last; `fixtures.CUMBERLAND_AESI`, its literal copy), `Well_Supply_pt` a single symbol #b7484b, `Explor_Other_pt`
categorized; Tehaleh.qgz: rule-based styles (11 of 14 rules unticked, two "IT" rules in different colours, "EP, TP"
at 90 % opacity). Tests use those styles as literals (`fixtures.categorized_renderer`, `rule_renderer`,
`single_renderer`) and never open the project files.

## Package layout

```
xsections/                      plugin folder (users: scripts/package.py zip; developers: install_dev.bat link)
  metadata.txt  __init__.py  plugin.py  icon.svg
  core/   model.py  units.py  section.py  explorations.py  others.py  build.py  mf6.py  mf6_section.py
          hover.py  surfaces_csv.py  symbology.py
  render/ scales.py  notes.py  figure.py  export.py  pdfprefs.py  _pdf_incremental.py  symbols.py (0.3.6)
  ui/     dock.py  widgets.py  point_guess.py  point_rows.py  mf6_dialog.py  maptools.py  preview.py  readout.py
          popup.py  map_feedback.py  surfaces_csv_dialog.py  settings_store.py  symbol_icons.py  problems.py (0.3.6)
tests/                          unittest; run with scripts/run_tests_parallel.bat (or run_tests.bat: one process)
  fixtures.py  test_*.py  data/mf6/  data/compat_032/ (the 0.3.2 golden files)
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
    # closestSegmentWithContext; direction = compass8 of (foot - point), the direction of projection (0.3.5,
    # decision 26; before: point - foot); top/bottom per decision 2;
    # flags e.g. "ExploElev 205.6 ft ignored: 454.6 ft from LIDAR", "station in a DEM gap"
def top_and_bottom(table_top, lidar, table_bottom, depth, settings) -> TopBottom
    # pure (no QGIS): (top, top_source, bottom, bottom_source, total_depth, flags) per decision 2
    # (0.3.3) find_explorations(..., ground=None, wl_table=None) reads ONE row: pass layer_view(settings, row)
def _project_points(line, layer, label_field, type_field, types, tol, crs, dist_factor, project,
                    what="explorations (points)") -> tuple[list[_Cand], list[str], int, int]
    # the one selection rule of explorations and other points (decisions 3, 22): (candidates, beyond, near, type index)
def _type_filter(layer, type_i, types) -> str           # "" in types = NULL or empty ("(no value)")
def date_text(value, epoch_ms=False) -> str             # epoch_ms for number fields: ms since 1970 -> "M/D/YYYY"
# (0.3.5, decision 24) numbers stored as text
def to_number(value) -> float | None                    # a text through text_number; NULL, nan -> None
def text_number(text) -> float | None                   # "642.3", " 642 ", "1e3", "1,234.5"; else None
def not_number_text(value) -> str                       # the trimmed text of a text that is not a number, else ""
def not_number_flag(field, text, then="left out") -> str   # 'DTW “dry” is not a number: left out'
def read_wl_table(settings, project) -> WlTable         # a dict by name_key, with .not_numbers and .warning

# core/others.py (0.3.3)
def find_other_points(line, layer, row: dict, settings, crs, sampler, dist_factor, project, ground)
        -> tuple[list[OtherPoint], list[str], int, list[str]]
    # (points sorted by (station, label), beyond, near, labels left out for want of an elevation); placement
    # line | lidar | field with the elev_empty fallbacks; flags GAP_FLAG, NO_LIDAR_FLAG, the 25 ft field check;
    # direction as a Hit's (foot - point, decision 26)
# (0.3.6, decision 27) Other features: line and polygon layers
def feature_kind(layer) -> str                  # "point" | "line" | "polygon" from the geometry type; "" otherwise
def feature_layer(layer_id, project=None)       # the valid point, line or polygon layer with this id, else None
def find_crossings(line, layer, row, settings, crs, sampler, dist_factor, project, ground)
        -> tuple[list[OtherPoint], list[str]]
    # (crossings sorted by (station, label), labels left out for want of an elevation): an OtherPoint of kind
    # "crossing" (offset 0, side and direction "") wherever the section line crosses or touches a line; a shared
    # stretch: one crossing at its middle flagged ALONG_FLAG (from ALONG_MIN_FT = 1 ft); placed by _place as points
def find_area_pieces(line, layer, row, crs, dist_factor, project) -> list[AreaPiece]
    # the stretches of the line inside each polygon, sorted by (start, label); merged where they touch, slivers under
    # MIN_PIECE_FT (0.01 ft) dropped; open_start / open_end when A / A′ lies strictly inside (ALONG_TOL_FT off its edge)

# core/model.py (0.3.3, decision 22): rows, pure
POINT_LAYER_DEFAULTS, OTHER_POINT_DEFAULTS, FLAT_LAYER_KEYS     # row keys in order; flat name -> row key
def clean_point_layer(d) / clean_point_layers(v) / clean_other_point(d) / clean_other_points(v) / clean_hidden(v)
def layer_rows(s) -> list[dict]                  # point_layers cleaned, else [row_from_flat(s)] (flat layer), else []
def layer_view(s, row) -> Settings               # s with the row's fields in the flat keys (per-row work)
def hit_settings(s, hit) -> Settings             # the view of the row a hit came from
def line_key(s) -> str                           # "layerid#fid" | "drawn" | ""
def hidden_key(line_key, layer_id, fid) -> str   # a left-off entry "LINEKEY|LAYERID|FID"
def point_legend_name(row, layer_name) -> str    # the row's name, else the layer's
def as_rows(s) -> Settings                       # s as the panel and a version 6 load give it (tests)
# SectionModel: hits (plotted only), left_off, point_layers [PointLayerInfo], other_points [OtherPoint],
#               other_layers [OtherLayerInfo], line_key; has_points = has_explorations or an other row on

# core/model.py (0.3.4, decision 23): sheet style keys and layer styles, pure
POINT_LOOKS = ("black", "gray", "color")         # color: each exploration in its colour in the layer's own style
STYLE_KINDS = ("single", "categorized", "graduated", "rule", "other", "none")
class StyleItem(key, label, color, on=True)      # one legend item with a symbol: QGIS's legend key, its label as
                                                 # the layer's legend names it, "#rrggbb", ticked in the Layers panel
class LayerStyle(kind="none", field="", name="", items=[])   # a point layer's style as read (items in legend order)
# Hit.style_rank (index in its row's LayerStyle.items, -1: no symbol, drawn black); Hit.color (a Color hit's colour,
# "" without a symbol); PointLayerInfo.style (Color rows: the LayerStyle as built; PointLayerInfo.color "" for them)
GRID_CHOICES = ("green", "gray", "custom"); GRID_STYLES = ("solid", "dash", "dot")
GRID_PRESETS = {"green": (("#5f9a72", 0.7, "solid"), ("#a8c8b2", 0.35, "solid")), "gray": ...}   # (major, minor)
GRID_W_MIN, GRID_W_MAX = 0.1, 3.0
DEPTH_LW_BLACK, DEPTH_LW_COLOR = 0.75, 1.6       # pt: Black and Gray rows | Color rows
DEPTH_LW_LIMITS = {"depth_lw_black": (0.25, 3.0), "depth_lw_color": (0.25, 4.0)}
# Settings: grid_color (green | gray | custom), grid_major_color / _width / _style, grid_minor_..., grid_custom_used,
#           depth_lw_black, depth_lw_color (all flat scalars; data_color is gone)
def grid_spec(s) -> ((major colour, pt, style), (minor ...))   # a preset's, or the cleaned custom keys
def depth_widths(s) -> (black and gray pt, color pt)            # clamped to DEPTH_LW_LIMITS, else the defaults
# core/model.py (0.3.5, decision 25): page orientation, pure
ORIENTATIONS = ("auto", "landscape", "portrait")    # Settings.orientation, after `sheet` (default "auto")
def clean_orientation(value) -> str                 # one of ORIENTATIONS (case and spaces ignored), else "auto"
def clean_sheet_style(data: dict) -> None                       # in place, on every load (migrate_settings)
# core/model.py (0.3.6, decision 27): Other features rows and guesses, pure (no settings version step)
OTHER_SHAPES = render.symbols.SHAPE_KEYS          # the catalogue's 30 keys and the legacy star
FEATURE_KINDS = ("point", "line", "polygon"); AREA_PLACES = ("inside", "above"); AREA_EDGES = ("off", "ground", "full")
AREA_STYLES = ("solid", "dash"); AREA_COLOR_DEFAULT = "#7a4fb0"
DEFAULT_SHAPE = {"point": "asterisk", "line": "stream", "polygon": "asterisk"}   # an unknown shape is cleaned to it
# OTHER_POINT_DEFAULTS gains kind, bracket, bracket_style, edges (after elev_empty); clean_other_point cleans kind first
def feature_row(kind="point", **kw) -> dict      # a new, cleaned Other features row of that kind
GUESS_KEYS = ("label_field", "type_field", "top_field", "bottom_elev_field", "depth_field", "screen_top_field",
              "screen_bottom_field", "wl_field", "wl_date_field", "atd_field", "atd_date_field")
# POINT_LAYER_DEFAULTS gains guessed=[] (last): the boxes guessed from their names, not checked yet (the row's
# "check" badge; Looks right clears it); clean_point_layer keeps GUESS_KEYS members, once each, in that order;
# layer_view, the build and FLAT_LAYER_KEYS ignore it
# OtherPoint.kind "point" | "crossing"; OtherLayerInfo.kind / bracket / bracket_style / edges (plotted counts points,
# crossings or pieces); AreaPiece(fid, label, type_value, start, end, open_start, open_end, layer_index, layer_id,
# layer_name); SectionModel.other_areas (sorted by (start, layer_index, label)); Plan.above_in (in, the band above)

# core/symbology.py (0.3.4, decision 23): QGIS core only, no widgets, no matplotlib
NEAR_WHITE = 230; NO_VALUE_LABEL = "(no value)"; OTHER_VALUES_LABEL = "(other values)"
def symbol_color(symbol, context=None) -> str   # "#rrggbb": fill, else outline (hollow or near white), else black
def layer_style(layer) -> LayerStyle            # kind, class field, the items with a symbol (label, colour, on);
                                                # reads no feature (the row editor)
def read_styles(layer, fids, project=None) -> (LayerStyle, {fid: (rank, colour)})
    # the symbol QGIS draws each feature with: symbolForFeature (single, categorized, graduated) or the last
    # matching legend item (rule-based, other), on a clone of the renderer; (-1, "") when it draws none

# core/build.py
def build_section(settings: Settings, project: QgsProject) -> SectionModel
    # resolves layers by id, runs everything above, fills warnings; raises SectionError with a
    # message fit for the panel (no DEM chosen, geographic CRS, line off the DEM, etc.);
    # no exploration row: a ground-only model (decision 9); every ticked row through layer_view, one sampler
    # and one ground profile; a ticked row whose layer is gone: SectionError naming the row; an other-points
    # row whose layer is gone: left out with a warning (decision 22); a Color row: read_styles once for all its
    # hits (plotted and left off), a style that can't be read: that row black with a warning (decision 23);
    # (0.3.6) an other row by its layer's kind: points, a line row's crossings (they join other_points), a polygon
    # row's pieces (other_areas); a layer of no kind left out with a warning (decision 27)

# core/hover.py (0.3.1; 0.3.3 additions)
def hover_targets(model) -> list                 # model.hits, then model.other_points (one hover index)
def hover_target(model, index)                   # None for -1 or out of range
def several_layers(model) -> bool                # more than one exploration row on
def hit_cells(hit, settings, model=None)         # two arguments: 0.3.2's output; with a model, the layer name
def other_cells(p, settings, model=None); def target_cells(t, settings, model=None)
def also_cells(targets, settings, model)         # the popup's "Also here" rows (up to 3, then "+N more")
def strip_cells(t, settings, model=None)         # (0.3.4) the strip's (title, value, small print, level kind):
    # target_cells, but a water level titled by its date ("Measured" / "ATD" without one), "11.3 below top", kind
    # "measured" / "atd" (its symbol); the popup keeps target_cells
# (0.3.6) crossings are other points (hover targets); their offset cell's small print is "crossing"; pieces are none
```

## render API

```python
# render/scales.py
SHEETS = {"letter": (11, 8.5, "Letter"), "tabloid": (17, 11, "Tabloid"), "ansic": (22, 17, "ANSI C"),
          "archc": (24, 18, "ARCH C"), "ansid": (34, 22, "ANSI D"), "archd": (36, 24, "ARCH D")}
MARGIN = dict(left=1.0, right=1.5, top=1.2, bottom=2.3)   # standard layout, 0.5 in printer edge
NOTES_MIN_W = 6.4                                          # width the scale bars + notes need (standard)
def margins(settings, z_range=None, types=(), block_in=0.0) -> dict   # inches, paper edge to frame
def notes_min_w(settings, types=()) -> float               # width the block under the plot needs
def plan(model: SectionModel, settings: Settings) -> Plan
def page_turns(settings) -> tuple[bool, ...]   # 0.3.5 (decision 25): the `landscape` flags plan() tries per
                                               # sheet: Auto (True, False), Landscape (True,), Portrait (False,)
# 0.3.3 (decision 22)
def hit_in_range(hit) -> bool                              # the row counts toward the automatic range
def runs_below(hit, z_min, settings) -> bool               # out of range, drawn, bottom below z_min (plan.z_min)
def td_text(total_depth) -> str                            # "TD 50'"
def td_labels(hits, settings, plot_length, ground=None, z_range=None, label_hits=None)
    # the labels of label_hits (default: hits), with the bars and marks of every hit as obstacles
class LegendEntry(text, kind, key=None, color="")   # (0.3.4) kind: layer|style|surface|screen|measured|atd|point
    # layer: a row by its legend name (key = the row index; color = a single-symbol Color row's swatch colour, else
    # ""); style: one colour of a Color row's style (key = the row index, color = the item's colour, text = its label)
def layer_entries(model, settings) -> list[LegendEntry]    # (0.3.4, decision 23) the rows and the Color rows'
    # colours (an identical label and colour once across the rows); z-free (only the hits and the settings), so
    # the plan and every sheet agree
def legend_entries(model, settings, z_min=None, z_max=None) -> list[LegendEntry]   # layer_entries, surfaces,
    # screen / water levels (with the frame: those drawn inside it), point rows; the label is always "Legend:"
def frame_levels(hit, z_min=None, z_max=None) / frame_screen(hit, z_min=None)   # what a frame draws of a hit
def td_page_layout(hits, settings, x_in, z_in, k, frame_w, y0, y1, z_floor, width_of, marks, crosses)
    # every TD label of a page (under the bars, beside the lines, beside the arrows); and those left out
def standard_block_depth(note_texts, entries, width_in) -> float   # the standard layout's notes and legend, inches
GROUND_LW = 1.1                                            # the drawn ground line, pt (moved here from figure.py)
class Capsule(ax, ay, bx, by, r)                           # a segment and a radius, inches: the ink of a symbol
def symbol_capsules(shape, size_pt, k=1.0) -> list[Capsule]; symbol_outline(...) -> polygon; symbol_extent(caps)
def capsule_top(c, x) / capsule_bottom(c, x) / stroke_top(xs, ys, r, x)       # exact envelopes
def rest_on_line(gx, gy, x_c, caps, r, gap, thin=False) -> float | None   # the symbol centre resting on a stroke
def ground_top_fn(stations, zs, x_in, z_in, r) -> top(left, right)   # the ground stroke's top over a span (exact)
def other_label_layout(xs, anchors, widths, k, frame_w, obstacles, ground_top=None) -> list[LabelSpot]
def other_label_top(model, settings, plot_length) -> float # the plan's room for the other-point labels, ft
class PlacedPoint(index, station, z, half_w, below, above, label_top)   # an other point as drawn (for the hover)
# 0.3.6 (decision 27): the symbol geometry lives in render/symbols.py (imported back here); brackets
def symbol_flip(model, p, settings) -> bool                # the spring's tail to the lower side (SPRING_FLAT_IN 0.005)
def other_label_boxes(model, settings, plot_length) -> (symbol boxes, label boxes)   # other points at sheet scale
class AreaSpot(index, place, level, text, label_x, line_z, top_z, lowered)   # a piece's bracket as laid out
class AreaFrame(scale, k, z_in, z_of, obstacles)           # a drawing of its own scale (the preview) for area_layout
def area_layout(model, settings, plot_length, z_cap=None, point_boxes=None, z_floor=None, frame=None)
    -> list[AreaSpot]                                      # stacking (shortest first, the longer above), inside / above
def area_top(model, settings, plot_length, point_boxes=None, z_floor=None) -> float   # the Auto range's room, ft
def area_band_in(model, settings, plot_length, scale=1.0, k=1.0) -> float   # Plan.above_in: AREA_FRAME_GAP_IN + rows
def area_warnings(model, settings, plot_length, z_max, v_major, z_min=None) -> list[str]   # "Brackets of … lowered"
# AREA_LW 1.0 pt, AREA_TICK_IN 0.06, AREA_ARROW_IN / _HALF_IN 0.06 / 0.035, AREA_LABEL_GAP_IN 0.02, AREA_PAD_IN 0.04,
# AREA_CLEAR_IN 0.05, AREA_STACK_GAP_IN 0.03, AREA_TOP_PAD_IN 0.02, AREA_FRAME_GAP_IN 0.03, AREA_ROW_IN 0.2218 in,
# AREA_DASH_PT (4, 2), AREA_EDGE_LW 0.6 pt with AREA_EDGE_DASH_PT (3, 2), CONTINUES " (continues)"; margins(...,
# above_in=0.0) grows the top by the band; display_label: a crossing is its name only

# render/symbols.py (0.3.6, decision 27): pure (math, typing)
class Symbol(key, name, group, color, rests=True, mirrors=False, legacy=False)
GROUPS; CATALOGUE (30, drop-down order); SYMBOLS (by key, the star too); CHOICE_KEYS; LEGACY_KEYS = ("star",)
SHAPE_KEYS; LEGACY_DRAWN (0.3.5's six, drawn by 0.3.5's code); FALLBACK_KEY = "circle"
def resolve(key) -> str; symbol(key) -> Symbol; usual_color(key) -> str; grouped() -> [(group, [Symbol])]
def glyph(key, size_pt, k=1.0, flip=False) -> [Stroke | Ring | Dot | Fill | Letter]   # paper inches, y up
def glyph_capsules(...) -> [Capsule]; glyph_bbox(...) -> (left, right, bottom, top); tint(color, f=0.2)
def symbol_capsules(shape, size_pt, k=1.0, flip=False)    # 0.3.5's for LEGACY_DRAWN, else glyph_capsules
```

`margins()`: the standard layout with notes keeps `MARGIN`, moved by the printer edge (0.5 in: `MARGIN`;
0.3 in: 0.2 in less on every side); its bottom grows when the notes and legend under the plot need more
(`block_in`: `plan()` works it out with `standard_block_depth` from the notes as they will read, wrapped at the
plot's width (the narrowest tile's), at least 6.4 in; never shallower than drawn), so the block never runs into
the printer edge. The compact layout, and the bottom without notes, are added up from
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
`types` the legend entries (rows at the least column width). `notes_min_w`: 6.4 (standard), the
scale bar + 0.25 + 3.6 in of notes (compact), the scale bar alone (no notes; + 2.4 in for a legend).

Rules in `plan()`:
- Grid = `settings.effective_grid()`. Plot length = `ceil(length / h_minor) * h_minor`.
- Auto z: `lo = min(ground, bottoms, tick bases, lowest TD label row)`, `hi = max(ground, tops, tick bases)`
  (since 0.3.3 the bottoms, screens, levels and TD labels of in-range rows only, plus LIDAR and field other
  points with their symbol; `z_max` also clears the other points' labels: decision 22);
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
  (That is `orientation` "auto"; "landscape" or "portrait" tries only that orientation, here and for tiling;
  a custom page ignores it: decision 25.)
- Does not fit and `tile` is on: tile horizontally on the largest allowed sheet (or the named one), landscape,
  else portrait (only the chosen orientation with Landscape or Portrait).
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
def draw_preview(fig: Figure, model, settings, plan) -> list[PlacedPoint]     # dock preview: fits the figure, same VE;
                                                                              # returns the other points drawn
def display_label(hit, settings) -> str                                       # "MW-3" or "MW-3 · 40 ft S"
                                                     # (offset and direction of projection, decision 26)
def layer_views(model, settings) -> list[tuple[str, Settings]]               # (row name, its view), rows with hits
def depth_sources_text(settings, td=False, views=None) -> str                 # one text per distinct row text, merged
# gids (for tests): CLIP_GID "xsections-below-frame", CLIP_TD_GID / CLIP_TD_HALO_GID, OTHER_GID "xsections-other",
# OTHER_LEAD_GID, OTHER_LABEL_GID / OTHER_LABEL_HALO_GID, LEGEND_LINE_GID "xsections-legend-line" (0.3.4: a layer
# or style legend swatch)
# 0.3.4 (decision 23): GRID_COLORS, MAJOR_LW, MINOR_LW derived from core.model.GRID_PRESETS; FRAME_LW = 0.9;
# GRID_DASH_PT = {"dash": (4.0, 2.0), "dot": (0.6, 1.6)} (absolute, pt on paper); DEPTH_LW = 0.75 and
# DEPTH_COLOR_LW = 1.6 (the defaults; the widths drawn come from depth_widths(settings)); RC pins
# "lines.scale_dashes": True
def draw_swatch(fig, model, settings, entry, x, y) -> None  # one legend swatch: layer / style a line in the
    # entry's colour at the Color width, else Gray or black at the black width; points, surfaces, levels as before
# 0.3.6 (decision 27): _symbol_artists(shape, ..., flip=False) draws a catalogue key primitive by primitive (the
# LEGACY_DRAWN six as 0.3.5); _Painter.areas() the brackets (after other_points(), before ends()), their edge lines
# (_edge_runs) and labels; draw_swatch kind "area" (a small bracket in the row's colour and line style, ticks solid);
# draw_preview lays the brackets out at its own scale (_Painter._area_frame -> scales.AreaFrame) and grows its band
# above the frame when needed. AREA_Z 5.5, AREA_EDGE_Z 2.6; gids AREA_GID "xsections-area", AREA_EDGE_GID,
# AREA_LABEL_GID, AREA_LABEL_HALO_GID, LEGEND_AREA_GID "xsections-legend-area", LEGEND_SYMBOL_GID
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
- Grid: explicit lines at multiples of each interval, as `model.grid_spec(settings)` gives them (Sheet style >
  Grid, decision 23). Presets: Green (the default) major `#5f9a72` 0.7 pt, minor `#a8c8b2` 0.35 pt; Gray major
  `#6e6e6e`, minor `#b4b4b4`, the same widths; both solid. Custom: the major and minor colour, width (0.1-3 pt)
  and line: solid, dashed (4 pt on, 2 pt off) or dotted (0.6 pt on, 1.6 pt off, round caps), the patterns
  absolute on paper (`GRID_DASH_PT`, divided by the width because matplotlib scales them with it), starting
  again at each line's start. Solid lines are drawn exactly as before (`solid_capstyle="butt"`, minor z 0.5,
  major z 0.6). Frame 0.9 pt black, whatever the grid.
- Ground: 1.1 pt black, broken at nodata; each gap has a dotted link between its edges and a small
  "NO DEM DATA" note under it. Optional light fill below ground drawn under the grid. Drawing order:
  top-to-bottom lines (3.5) < TD halo (4.4) < ground (4.45) < TD text (4.5) < ticks < labels < match notes.
- Bends: thin dashed vertical line at each bend station, "BEND" above the frame. Optional:
  `Settings.show_bends` (default on; panel: Sheet style > Draw bend lines), sheet and preview alike.
- Top-to-bottom line (if on and top and bottom exist): dark gray (#2b2b2b) at the black width (Sheet style >
  Depth lines, `depth_lw_black`, 0.75 pt by default); small cross-bar (0.08 in) at the bottom, and the same bar
  at the top when the top is more than 0.04 in from the ground line (decision 7), both as wide as the line. If
  top is below the ground at the station by more than 0.05 in on paper, a dotted link (0.6 pt) from the ground
  down to the top. A row drawn Gray (#8a8a8a) uses it for the line, bars, link, tick, name and TD, at the black
  width. A row drawn in Color (decision 23) draws each exploration's line, bars, top cap, link and frame arrow
  in the colour of its symbol in the layer's QGIS style, at the Color width (`depth_lw_color`, 1.6 pt by
  default), with black ink: tick, name and TD stay black; an exploration its style draws with no symbol is
  drawn as a black one. The first row is drawn on top (decision 22).
- TD label under each bottom bar (decision 8): "TD 50'", 6.5 pt, rows 0.12 in apart, at most 3.
- Below the frame (an out-of-range row, decision 22): the line ends at the frame bottom with a chevron
  (0.03 in half width, 0.04 in tall, tip 0.015 in above the frame, miter joins, z 3.5) and the TD 0.045 in
  right of the line on a baseline 0.03 in above the frame, with a halo; no bottom bar.
- Other points (decision 22): the row's symbol (asterisk strokes with round caps, or a filled shape with a
  0.6 pt white edge and round joins) at z 4.8 (over the water levels 4.6, under the ticks 5): resting on the
  ground line with 0.1 pt to spare, or centred on its LIDAR or field elevation with a dotted lead (0.6 pt)
  from the ground line when more than 0.05 in below it; the name 7 pt, horizontal, with a halo, above it
  (0.02 in) and at least 0.05 in above the ground line, raised clear of the others with a 0.4 pt leader.
  Since 0.3.6 (decision 27) the symbol is any key of `render/symbols.py` (the old six drawn as before), and a line
  row's crossings are drawn the same way.
- Brackets (decision 27): a polygon row's piece as a 1 pt line in the row's colour (solid, or dashed 4/2 pt) with
  0.06 in end ticks, or an open arrow at an end past A / A′ with " (continues)" after the label; the label 7 pt in
  the row's colour with a halo, 0.02 in above the line, z 6; the line, ticks and arrows z 5.5; in the frame (above
  the ground and the labels in its span, 0.05 in clear, stacked 0.03 in apart) or in rows of 0.2218 in over the
  frame (the top margin grows by them, the end letters, BEND labels and titles move up). Edge lines: 0.6 pt, dashed
  3/2 pt, z 2.6, to the ground or the frame bottom.
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
  notes (`show_notes`; without them the legend stands beside the bar).
- Compact layout (decision 10): one title row and one end-letter row (`compact_rows_in`), the band under
  the distance title (`bottom_band`) with the bar, "HORIZONTAL" after it and `compact_notes` beside it,
  the vertical bar `vbar_dx_in` right of the frame. `compact_notes` gives each line as ranked parts
  (line 1: H and V scales, VE, grid, sheet; line 2: ground (DEM name, no datum: the elevation title has
  it), explorations, depth sources, "TD = total depth" and the label-offset explanation ("Labels: distance and
  direction projected onto the line", decision 26) when those marks are drawn). `fit_compact_notes`: whole
  lines at 5.8, then 5.5 pt with the bar under the plot's left end;
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
     line are projected perpendicular onto it." (+ "Labels give the distance and direction each exploration was
     projected onto the section line." only if offsets are labelled, decision 26; the explorations sentences only
     with an explorations layer) + when any line is drawn, the sources
     configured: "Tops: ExploElev where available, otherwise LIDAR at the exploration. Bottoms: BotElev
     where available, otherwise top minus ExploDepth." (adapted to `top_mode` and the empty fields; with rows
     whose texts differ, "… in A and B; … in C.") + "TD = total depth." when TD labels are drawn (clipped TDs
     too) + one sentence per other-points row and, when a well runs below the frame, the arrow sentence.
- Tiles: match line (dashed, dark red) at `match_left/right`, drawn under the ground and the data, with
  "MATCH LINE STA 32+00 · SEE SHEET 2 OF 3" (on two lines, or smaller, when the plot is too short for it;
  always 0.1 in inside the frame); overlap band lightly shaded. The note never covers a TD label, an
  exploration tick or label or a bar when any spot allows it, and keeps off the top-to-bottom lines and
  the ground line where it can (its white halo would cut them): candidates along the line in 0.05 in
  steps are scored in that order, then by form (one line, then two, then three shorter lines), side
  (core side, then the overlap band) and nearness to mid-height (`figure._Painter._match_note`).
- Legend ("Legend:", decision 23): a Color row's colours as its layer's legend names them, the rows by name when
  they are drawn differently, the surfaces, screens, water levels and other points; layer and style swatches are
  lines at the width their lines are drawn at.
- Notes are drawn one text per wrapped line at a fixed pitch (6.3 pt x 1.3), 0.035 in between notes.
- The left elevation title keeps the printer edge from the page edge (moved closer to the tick labels if
  needed).

## ui

- Toolbar button toggles the **XSections** dock (right). A second dock **XSections preview** (bottom)
  holds `ui/preview.py`: a toolbar, the hover readout strip (`ui/readout.py`), the optional popup
  (`ui/popup.py`) and a `FigureCanvasQTAgg` in a zoomable scroll area showing `draw_preview` (decisions 20, 21).
  The readout strip is compact since 0.3.4 (decision 23): one row of equal tiles (about 45 px) down to a 700 px
  preview, the first tile "760 ft from A" over the cursor's elevation and depth, "Ground", then each surface;
  numbers never cut, labels, details and names with "…".
- Panel sections (0.3.6, decision 27, the approved panel mockup; before: decisions 17 and 22). `ui/widgets.py`
  holds the visual system: `CollapsibleSection` (a `SectionHeader` tile or bar with its summary chip and amber
  count chip, a `SectionBody` on its navy rail that paints the open cards' Flare bands), `Subsection` /
  `SubsectionHeading`, `field_label`, `pair` and `checkbox_grid` (they stack in a narrow panel), the pills
  (`Disclosure`), `LayerCard` (+ `link_cards`, `paint_flare`), `RowTabs`, `Hint` / `Readout` and Verbose, the check
  badge, card and host, the swatches, `SegmentedControl` with the QComboBox API the code uses, `theme_for` (the
  mockup's light and dark tokens) and `panel_stylesheet`. Top to bottom: Line (Layer | Feature; Pick, Draw,
  Selected; Ends A to A′, Reverse, Save to layer), Surfaces (the Ground card with the DEM and band, a card per
  other surface, + Surface, + Bands…, + MODFLOW 6…; the Units & datum pill), Explorations (Layers: the exploration
  rows, + Add layer; All layers: Within | Labels, Label text; Depths: Depth line, TD label, Tops from, the Checks
  pill; Water & screens: Draw them, Print beside Off | Elev. | + date; Plotted), Other features (its rows of point,
  line and polygon layers, + Add layer), Scale & sheet (Scale: Horizontal | Vertical; Elevations: Auto | Manual,
  Split across sheets, Lowest | Highest under Manual; Sheet: Size | Format, Orientation Auto | Landscape | Portrait
  (off for a custom page: decision 25), Title, the Distances & printers pill), Sheet style (Grid: Look Green | Gray
  | Custom, Spacing from the scale and the spacing when unticked, Fill sheet | Below lowest; Depth lines: Black &
  gray | Color, Reset; Page: Printer edge, Compact layout, Notes, Bend lines, Shade below ground). Several may be
  open at once; all closed when the dock is created, reopened, or a project is loaded or cleared; never saved. A
  closed section is a solid tile, an open one the navy bar (#193340 light, #2f5a6f dark, fixed: no longer the
  palette's highlight). Under the scroll area the status line (a dot, the message or "Ready · …"), then the action
  bar: Refresh, ⋯ (Export points CSV…, Save line to layer, then Verbose, checkable), Export… The widgets start from
  `Settings()`.
  Widgets: `QgsMapLayerComboBox` (filtered by geometry/raster), `QgsFieldComboBox` (allow empty where
  optional), `QgsRasterBandComboBox`,
  `QgsDoubleSpinBox`. Type values: a checkable list (`point_rows.TypeList`) counted in one scan of the layer.
  Field defaults guessed from whole names (`ui/point_guess.py`), ignoring case, spaces and punctuation (`_`, `-`,
  `.` …) and a trailing unit in parentheses ("GW Elev. (ft)" is GW_Elev; 0.3.5, decision 24), never
  from a part of a name and never the layer's primary key (label: ExploName, AESI_MapLabel, ExploID, Name,
  MapLabel, Label, ID; type: ExploType_resolved, ExploType, Type; top elevation: ExploElev, TopElev,
  Top_Elev, GroundElev, GS_Elev, SurfElev, Elevation, Elev; bottom elevation: BotElev, BottomElev,
  Bottom_Elev, BOT_ELEV, BtmElev, TD_Elev, TDElev, BOH_Elev; total depth: WellCompleteDepth, ExploDepth,
  TotalDepth, Total_Depth, TD, Depth, Depth_ft, TD_ft, Depth_BOH; the water fields and the rest: decision 22; the
  number boxes list number and text fields, `widgets.NUMBER_BOX_FILTERS`, and guess number fields first: decision
  24). Guesses fill a new row or a layer newly chosen in a row; an
  optional field saved empty stays empty (none).
  Layers in a fresh project: a section line layer only by name (section, xsec, x-sec, profile,
  transect), never an arbitrary line layer; a DEM by name, else the first single-band raster not named
  like a photo or hillshade; the exploration and Other points rows by name (decision 22). Removing the last
  row is the ground line only, kept when layers are added. Layers added later (`QgsProject.layersAdded`): a
  box that is still empty, and a row list that is still empty, gets the same guess from the new layers; a
  row whose layer is missing takes back an added layer of the same name. Guesses never mark the settings as
  the user's (they are not saved by themselves).
- **Point-layer rows** (`ui/point_rows.py`, decision 22; cards since 0.3.6, decision 27): `ExplorationRow` and
  `OtherPointsRow` (Other features: point, line and polygon layers) in a `PointRowList` (no frame, 4 px apart, its
  section's body painting the open card's band: `set_band_host`), each a `LayerCard`: a header (tick, swatch: the
  look, the symbol or the bracket mark; the legend name and a subtitle such as "ExploName · 3 of 12 types · black",
  "lines · Name · 2 crossings"; the check badge; ⋯ Move up / Move down / Remove; under it the amber problem line)
  and an editor opened by a click on the card. An exploration row's editor has the tabs Layer | Depths | Water
  (`show_tab`), an Other features row's the controls of its kind (the symbol drop-down `SymbolCombo`). A row never
  loses what it was given: while its layer or table is missing (amber), or while layers are being removed,
  `value()` writes back what it stored, with only the header applied. Filling in code is silent (`changed` only for
  the user's edits); a type list scans its layer when the row's layer or type field changes and on Refresh, never
  on a rebuild. `set_problems` (from the dock, `ui/problems.py`), `confirm_guess` (Looks right), `checksChanged`.
  `PlottedList` (the Plotted subsection): "PLOTTED" with Show all in its heading, "N of M" beside it with Verbose,
  the old title "Plotted explorations (N of M, K left off by you)" as its tooltip (`text()`); one group per row,
  sorted by station, each entry "300 ft · 40 ft L", unticked ones struck through; the dock keeps the entries
  (`_hidden`).
- **Drawn in and the style box** (0.3.4, decision 23; `ExplorationRow`): `look_seg` Black | Gray | Color (tooltips
  "Black, like your own explorations", "Gray, to set this layer apart", "Each exploration in its color in this
  layer's style in QGIS"), in `field_box("Drawn in", ...)`; no colour button (Other points rows keep theirs).
  Black and Gray show `look_hint`: "Black by default, like your own explorations. Gray sets this layer apart;
  Color takes each exploration's color from this layer's style in QGIS." (0.3.6: that sentence is the tooltip of
  Drawn in; the Verbose hint reads "Black like your own explorations; Gray sets a layer apart; Color takes each
  exploration’s color from the layer’s style in QGIS.") Color shows `style_box` (a `LayerStyleBox`, frame
  `xsStyleBox`) instead:
  - `head`: "From the layer's style in QGIS: **Single symbol**" | "**Categorized by {field}** · {n} categories" |
    "**Graduated by {field}** · {n} ranges" | "**Rule-based** · {n} rules" | "**{renderer name}**" (another
    kind) | "no symbols (the lines are drawn in black)" | "the layer is not in the project." | "no layer
    chosen." (n counts every item, on or off; "1 category", "1 range", "1 rule"; a style that cannot be read
    shows as no symbols, as the build draws it in black);
  - `chips` (`widgets.StyleChips`: painted, wrapping; an 11 px circle in the colour with a 1 px #232323 border,
    the label at 0.9 × the font, cut with "…" only when wider than the row, every label in the tooltip): a single
    symbol one chip, "every exploration"; else the items that are on, those plotted on this section first (the
    dock passes their keys after each build, `set_plotted_styles`), then the rest in legend order, up to 4, then
    a muted "+ N more" for the other items that are on;
  - `off_note` (hidden at 0): "{k} switched off in QGIS: their explorations are drawn in black.";
  - `foot`: "Change them in Layer Properties > Symbology; the sheet follows." (not for a single symbol, no
    symbols or a missing layer; since 0.3.6 a Verbose hint, and the box's tooltip).
  The row reads its layer's style (`symbology.layer_style`) when a layer is applied, on a look change, on
  Refresh and when the layer's style changes (`refresh_style`). The header swatch (`ExploSwatch.set_colors`):
  Black and Gray their colour; Color the first three chip colours as vertical bars (one colour: the line and cap
  as before), black when there is no chip (no style, no symbols, a missing layer, every item switched off); the
  subtitle part "color from the layer style" for Color, "gray" for Gray, nothing for Black.
- **Following the style** (dock): `_track_layer_signals` connects `styleChanged` of every exploration row's layer
  (`_explo_layer_ids()`, whatever the look) beside the 0.3.3 signals, kept in `_layer_conns` so untracking
  disconnects it; `_on_rows_edited` tracks again when a layer it already watches for another reason (an Other
  points row, a table of water levels) is picked in an exploration row. `_on_point_style_changed(layer_id)` calls
  `refresh_style()` on that layer's rows and schedules a rebuild only when one is visible and in Color; it
  never marks the settings as the user's (nothing is saved).
- **Sheet style** (0.3.4, decision 23; `dock._build_style_group`, in the mockup's order; regrouped in 0.3.6,
  decision 27, into the subsections Grid, Depth lines and Page):
  1. *Grid* › Look Green | Gray | Custom (tooltips "Green engineering pad (the default)", "Gray, for
     black-and-white printers", "Your own colors, widths and line styles");
  2. under Green or Gray, `grid_info`, one muted line: a short line in the major colour, "Major 0.7 pt", one in
     the minor colour, "Minor 0.35 pt", then "solid" (0.3.5: "solid · the default");
  3. under Custom, `grid_custom_box`: a small table, columns Color / Width / Line, rows Major and Minor, with a
     colour button each (no opacity, no menu), a width spin (0.1-3 pt, 2 decimals, 0.05 steps) and an icon-only
     Solid | Dashed | Dotted control (`widgets.LINE_STYLE_ICONS`, 22 × 8 icons, accessible names Solid, Dashed,
     Dotted); under it the Verbose hint "Major lines every inch, minor every tenth." ("Major and minor lines at
     the spacing below." with the automatic grid off) and "Start from Green · Gray" at the right;
  4. (0.3.6) *Spacing from the scale (1 in, 0.1 in)* (`grid_auto`) and, only while it is unticked,
     `grid_spacing_row` (Horizontal, ft and Vertical, ft: major / minor), then Fill sheet Off | Below | Both |
     Below lowest, all moved here from Scale & sheet and the old Sheet style rows;
  5. *Depth lines* (the subsection heading, Reset at its right: "Back to 0.75 pt and 1.6 pt"; the NEW badge is
     gone), then *Black & gray* (0.25-3 pt) and *Color* (0.25-4 pt) spins and the Verbose hint "Which layers are
     black, gray or in color is set for each layer, under Explorations › Drawn in."; the spins and Reset are
     enabled only with the depth line on;
  6. *Page*: Printer edge, the four check boxes and the Verbose hint "The defaults leave the most room to draw
     and the paper clear for colored pencil." (0.3.5's dashed rule is gone).
  The first Custom starts from the preset in use (`_grid_last_preset`, tracked because `currentIndexChanged`
  fires after the old index is gone) unless the project has used Custom before (`grid_custom_used`); Green and
  Gray never change the custom widgets. "Start from Green / Gray" and Reset set their widgets quietly, then mark
  one user change (one save, one rebuild). The header chip: "Defaults" when every style key is at its default
  (`STYLE_KEYS`: the grid choice, the two widths, shade, bends, layout, edge, notes, fill; the custom values only
  count under Custom), else "Green grid" / "Gray grid" / "Custom grid", plus " · lines 1 / 2.25 pt" when the
  widths are not 0.75 / 1.6. A fresh or cleared project starts from `Settings()`: Green, 0.75 / 1.6,
  `grid_custom_used` False; nothing is written to QgsSettings.
- Section line: line layer combo + feature combo, **Pick on map**, **Draw on map**, **Use selected**,
  **Reverse**, end labels (0.3.6: Layer | Feature, Pick, Draw, Selected, then one Ends row: A to A′, Reverse,
  Save to layer at the right). Draw tool = port of `QgsMapToolProfileCurve` (`QgsMapToolCapture`,
  CaptureLine, `layer()` returns None, emits the captured curve; snapping and CAD dock work).
  Pick tool = `QgsMapToolIdentifyFeature` / `QgsIdentifyMenu.findFeaturesOnCanvas` on line layers.
- Map feedback (`QgsRubberBand`): section line, flat-cap swath (`buffer(tol, 8, Flat, Round, 2)`),
  plotted explorations and other points highlighted (not the ones left off); since 0.3.6 a line row's crossings
  too, as other points; polygon pieces are not highlighted. Cleared on unload.
- Top-to-bottom line group (0.3.6: Explorations › Depths): [x] Depth line; [x] TD label (TD 50'); Tops from (Table,
  else LIDAR at the exploration / LIDAR at the exploration / Table only); the Checks pill: 0 means missing, Ignore
  a table top off LIDAR by over [25] ft. The Top elevation, Bottom elevation and Total depth fields (all optional)
  are in each row's Depths tab, with the Verbose hint "Top from the table, else LIDAR; bottom from the table, else
  top − depth."; and a sources readout ("Tops: 5 ExploElev, 3 LIDAR · Bottoms: 2 BotElev, 6 top − ExploDepth, 1
  none").
- Readouts under each group: length / vertices / bends / direction with azimuth (hint to Reverse if
  A′ bears 135–315°), DEM coverage and gaps, plotted count / near count / beyond ends / flags (or
  "No explorations layer: ground line only"), top and bottom sources,
  VE / plot area / elevation range / grid below lowest point / sheet and tiles / fit warning.
  Since 0.3.3: "Plotted N: n1 name1, n2 name2" with several rows on (· K left off by you), the wells below the
  frame in amber ("HW-1 runs below the frame (TD 254′)", "3 run below the frame: …"), flags with the layer
  when several rows are on, "No exploration layer is on: ground line and surfaces only."; Other points per
  row ("Seeps: 4 plotted · …", then one line per point when there are 6 or fewer). Chips: "N plotted",
  "2 of 3 on · N plotted", "Layer missing" / "2 layers missing" (amber), "Off", "None".
  Since 0.3.6 (decision 27) the readouts are Verbose notes (`widgets.Readout`): a real problem (flags, values that
  are not numbers, a layer gone, DEM gaps, a surface left out) is its row's amber line and check card instead
  (`ui/problems.py`), and the Other features count adds areas ("… and N more flags" after six). The Depths and
  Screens & water chips went with their sections; each section's amber count chip counts its cards with a badge.
- Any change (including a new project or layer CRS) -> debounced (300 ms) rebuild + preview. Errors
  (`SectionError`) show in the status line (0.3.6; the message line before), never a traceback dialog;
  `Plan.warnings` and model warnings no row covers show there in amber (`problems.status_warnings`), else "Ready ·
  …". Lowest | Highest are shown only under Manual (0.3.6; before, disabled in Auto, they showed the auto limits).
- File errors (a PDF or CSV held open by another program) become a message-bar warning. Unreadable
  saved settings fall back to defaults value by value; a failed restore never half-loads the plugin.
- The preview toolbar (decisions 20, 21): Fit, Zoom out, the zoom percent, Zoom in, Surfaces CSV…, and the
  Readout row and Popup toggles. No Save: the preview is not to scale; files come from Export….
- **Export…**: file dialog (PDF/PNG/SVG; default name "Section A-A' H1000 V50.pdf"), then `export()`;
  message bar with the file path(s).
  **Save line to layer** (memory layer "XSections lines": start, end, h_scale, v_scale, tolerance).
  **Export points CSV** (one row per plotted Hit, left-off ones out, with top_source, bottom_source (field,
  shifted, depth or none), depth_ft = top − bottom, total_depth_ft, screen_top_ft, screen_bottom_ft and
  water_levels, e.g. "652.8 measured 6/12/2025; 640.1 ATD", and `layer` last: the row's legend name; other
  points, crossings and pieces are not written).
- Settings persist in the project: `QgsProject.writeEntry("xsections", "settings", settings.to_json())`,
  restored on project load (older versions migrated, see decisions 2, 14, 22 and 23). Per-user conveniences (the
  last export folder, Verbose since 0.3.6) go to QgsSettings under `xsections/` (`settings_store.user_value`).
- Qt6 rules: fully qualified enums (`Qt.AlignmentFlag.AlignLeft`), `exec()` not `exec_()`, import Qt via
  `qgis.PyQt`, no PyQt5 imports, no compiled resources (icon by file path). `unload()` removes every
  action, dock, map tool, rubber band and signal connection.

## Tests (unittest, headless)

`scripts/run_tests_parallel.bat` (2026-10-09) runs the suite in min(6, CPUs - 1) processes through the OSGeo4W
`python-qgis.bat` (`scripts/run_tests_parallel.py`; `--workers N`, `--serial`, `--plan`; module, class or test names
as arguments run just those, in parallel when more than one): about 3.5 minutes for the full suite instead of 10-15.
Each worker is a plain `python -m unittest -v <names>` with the environment of `run_tests.bat` (plus
`PYTHONUNBUFFERED=1`, `XSECTIONS_TIME_FACTOR`, its own `MPLCONFIGDIR` seeded with a copy of the font cache, and the
run's `XSECTIONS_RUN_TAG`), its output in its own log under `%TEMP%\xsections_tests\run_*` (with `summary.txt` and
`times.json`). The launcher reads each worker's -v stream as it arrives (a test starts when its line reaches the
pipe, ends when its status does) for per-test, per-class and per-module times, which it remembers in
`%TEMP%\xsections_tests\durations.json`; modules go longest first to the least-loaded worker, and one longer than
0.6 of a worker's fair share (and 20 s) is split into its classes and such a class into its tests
(`test_layout.EveryCombination`'s three tests take 42-121 s each). Splits follow unittest's own loader, not the
source: before the workers start, one process (the launcher with `--list-tests`, ~3 s) loads the names and reports
every test id, and a module or class may be split only where loading each of its classes or tests alone gives
exactly the tests of the whole (so `test_compat_032.Compat032`'s 15 tests made at import time are all there; a class
imported from another module, or tests made by `load_tests`, keep their module whole; without the list nothing is
split). At the end every listed test must have started in a worker (or be explained by a set-up error or skip of its
class or module, or a crashed worker), else the run fails (`not run=k`), and the times are remembered only from such a
complete run (fix stage of 2026-10-09: before it, a run planned from partial times could drop the generated tests
and still end `OK`). The summary gives every worker (with its exit status) and module with its time and each failure
with its traceback, and ends like unittest's (`Ran N tests in X s`, `OK` / `FAILED (...)`, `NO TESTS RAN` with exit
5 when nothing ran; exit 0 only when all passed). A worker passes only when its exit status is the one `python -m
unittest` gives for the result it printed (0 for OK, 1 for FAILED, 5 when no test ran and none was skipped): one
that prints OK and then dies, say in QGIS's shutdown, fails the run as a crashed worker, as `run_tests.bat` would.
A worker is never waited for without end once it has printed its result (hang fix of 2026-10-09: one python3.exe,
after unittest's `sys.exit(0)`, stayed stuck in Windows' tear-down of the process, its handle never signalled and
its pipe never closed, taskkill powerless, and the launcher waited for ever): when its output holds unittest's final
result (`Ran N tests`, then the verdict) and nothing new comes for `RESULT_GRACE` (30 s times its time factor) while
the pipe is still open, its exit status is read without waiting (ctypes `GetExitCodeProcess` on the process handle,
`poll()` elsewhere) and, when it has one, used under the rules above (the summary notes "worker N's process did not
end after its result (Windows); exit code X used"); still `STILL_ACTIVE` after `EXIT_GRACE` (60 s) more, it is
killed as far as it can be and counts as hung after its result: the run fails (`hung workers=k`, the worker, its log
and its PID named). Nor is one waited for without end before its result (deadline of 2026-10-10): a worker that
has exited without unittest's result while a process it started holds its pipe is taken as ended with that exit code
once nothing has come for `RESULT_GRACE` (`check_open`, `Worker.cut_without_result`; not the listing process): a
crash without a result ("ended without a result (exit code N) (its output was still open: held by a process it
started?)"). And every worker, the serial re-run too (planned by `make_units`, so it has estimates), has a deadline:
`max(WORKER_DEADLINE_MIN, WORKER_DEADLINE_K x planned)` (900 s, 4 x the estimates of its names) times its time
factor, 2,700 s for a parallel worker planned at ~130 s and ~3,000 s for `--serial`, while the longest worker takes
~140 s and the longest test ~123 s. One still running then (`check_deadline`) is killed (or noted as already exited,
another process holding its output) and fails the run as timed out (`timed out workers=k`; the worker, its PID, its
log and the last test it started named; `--plan` shows each worker's deadline).
The listing process (it starts and ends QGIS too: the test modules call `start_app` at import) is
read the same way, never with `communicate()` or `wait()` without a timeout (before, `subprocess.run(timeout=...)` did
not bound it on Windows: after the timeout's kill it waited for the pipe's end): once its line of JSON has come whole
and nothing more for `LIST_GRACE` (10 s) while its pipe is open, its exit status is read without waiting (it is
killed when it has none `EXIT_GRACE` later) and its list is used, with a note (it is no worker: the run does not fail
for it); `LIST_TIMEOUT` (300 s) after its start it is given up (killed if it has not exited), and the run goes on
without a list. Each process carries a tag of its own under the run's (`<run>_w<n>_`, `_list_`, `_rerun_`), so
the end-of-run clean-up (and `--plan`'s) leaves the `RUN_TMP` folders of a process that has not ended in place and
lists them.
Timing tests (`fixtures.timing_test`: the budgets, the waits for the panel's 300 ms timer, the hover speed) multiply
their limits and waits by `fixtures.TIME_FACTOR` (`budget()`, `wait_ms()`), from `XSECTIONS_TIME_FACTOR`: 3 under the
parallel launcher, 1 otherwise, so a serial run checks them exactly as written. When several processes ran, every
test that failed is run once more, alone in one process with the factor 1; the serial result decides only for a test
tagged `@timing_test` (the launcher finds the tags in the source with `ast`), any other failure stands. A run in one
process (`--serial`, `--workers 1`, a single name) is never run again: its result stands. Ctrl+C ends the workers
(waiting for each) and removes the run's temp folders.
Isolation (audited 2026-10-09): `RUN_TMP` and the QGIS profile (`QgsSettings` and plain `QSettings` alike) are
per process (`mkdtemp`); the dense fixture's cache is one file in `%TEMP%\xsec_cache` written under a per-pid name and
renamed (`os.replace`), so concurrent first runs never open half a file; the real data and `tests/data` are only
read (tests that change a model copy it to `RUN_TMP` first) and his GeoPackage only through a byte copy (already the
rule); `test_package` builds into
`RUN_TMP`; no test uses a fixed port or a fixed temp name; matplotlib's font cache is per worker (above). A test
process cannot remove its own `RUN_TMP` at exit while QGIS still holds the profile's `symbology-style.db`: the
launcher removes its processes' folders (named by the run's tag) once they have ended; `run_tests.bat` still leaves
its ~1 MB `xsec_run_*` folders in `%TEMP%` (three a full run: its own and the two 250 % child processes'). Golden files are never made in parallel: with
`XSECTIONS_MAKE_GOLDEN` or `XSECTIONS_REMAKE_GOLDEN` set the launcher refuses (exit 2). `test_parallel_runner.py`
covers the launcher (its reading of a -v stream made by unittest itself, a worker's exit status, the re-run verdict
and that one process is never run again, the tags, the listing and the splitting along it, the not-run check,
Ctrl+C, the refusal, a worker's environment; `main()` runs there with its processes replaced; a worker that prints
its result and then keeps its pipe open, with small child scripts and graces of a second: one that sleeps holding
stdout is killed and counted as hung, one that exits with a code while a child of it holds the pipe has that code
used, and `GetExitCodeProcess` is read on real processes; one that exits without a result while a child holds its
pipe counts as crashed within its grace, one stuck in its test past a deadline of 2 s is killed and timed out (or
noted as already exited), and with `main()`'s processes replaced a timed-out worker or serial re-run fails the run;
likewise a listing script that prints its list and then never exits, or exits while a child holds its pipe, or
prints nothing and holds it: `list_tests` returns within its graces or `LIST_TIMEOUT`, with the list when it came
whole) and `TIME_FACTOR`.
**The test command of the build specs' Hard rules is now the parallel one**, from Git Bash in one Bash call:
`cd /c/Users/lukem/Python/Projects/qgis-xsections && export PYTHONDONTWRITEBYTECODE=1 XSECTIONS_REALDATA="<the
copied real-data folder>" && cmd //c "scripts\\run_tests_parallel.bat"` (module names after the .bat for a part;
`timeout: 600000`; on a busy machine run the full suite with `run_in_background: true`).

`scripts/run_tests.bat` (one process, kept) runs `python -m unittest discover -s tests -v` through the OSGeo4W
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

`test_hover_csv.py`, `test_preview_tools.py`, `test_map_cursor_csv_dialog.py` and `test_preview_wiring.py`
(0.3.1) cover the hover values (equal to the drawn arrays, nan past the ends and in gaps), the readout slots
and height (unchanged over many hovers), the zoom (inches fixed, the point under the mouse kept, no re-layout),
the map cursor and map-to-preview hover (beyond the ends ignored, nothing left after unload) and both CSV
layouts; with real data, the CDF section is hovered, zoomed and exported. `test_mf6.py` and `test_mf6_section.py` (0.3.0) cover the MODFLOW 6 readers and sampling with three small real
models in `tests/data/mf6` (DISV, rotated DIS, DISU; run with mf6 6.7.0, regenerated by `make_fixtures.py`) and,
with real data, the user's F9_flowV1 (DISV) and CDF_Mounding (DISU) runs. `test_wells_surfaces.py` (0.2.0) covers the other surfaces (stored settings cleaned, cells traced exactly to the
cell edges, smooth sampling, warnings instead of errors, the elevation range with and without `in_range`, lines,
marks clear of the explorations, legend) and the screens and water levels (`screen_and_levels` rules for
depths and elevations, left-out values, the table of water levels and its kinds, dates, the drawing: brackets,
leaders from mid-screen, open and filled triangles with their tips on the levels, labels that never overlap, the
points CSV). `test_panel.py` covers the 0.2.0 panel (all sections closed, segmented controls, round trip of
every new setting, surface rows, header chips).

0.3.3 (decision 22). `test_compat_032.py` keeps old projects looking exactly as before: golden files of five 0.3.2
projects (`tests/data/compat_032/`: the version 5 settings, every hit, the plan, the model's warnings, and every
sheet and preview as PNG), made once from the untouched 0.3.2 tree and never regenerated without the user, are
compared through `Settings.from_json`, `settings_store.load` and the panel, the PNGs pixel for pixel.
`test_point_layers.py` covers the cleaners and row helpers and the build of several rows (the sum of each row
alone, no de-duplication, each row its own fields under the shared rules, one row equal to the flat shorthand, a
shared table read once, a missing row's error), the left-off list, the type filter with "(no value)", the
epoch-millisecond dates and the budgets on the 32,000-point GeoPackage fixture (`fixtures.make_dense_layer`);
`test_other_points_core.py` the selection, the placement with every fallback, the flags and a missing layer left
out. The dense fixture is made once and kept in the system temp's `xsec_cache`, under a name keyed by its
generator (a copy in each run's folder was left behind whenever OGR still held it). `test_render_layers.py` covers the looks, the layer legend, the elevation range with rows left out of it, the
frame arrow and its TD, and the notes per layer; `test_other_points_render.py` the symbol geometry, the resting
check (measured from the drawn artists, on the plane and the terrain DEM at VE 10 and VE 1, in the sheet, a 300 dpi
PNG and the preview), the LIDAR and field placement with its lead, and the labels. `test_point_rows.py` covers the
field guesses on his real field names and the row widgets on their own (round trips in key order, nothing lost
while a layer or table is missing, silent filling, budgets); `test_panel_layers.py` the dock's rows (guessed,
added, moved, removed, missing), the left-off list as it follows the line (another line, Show all, Reverse, a new
drawing, Save line to layer, a layer added again), the readouts, chips and the points CSV, the layer signals, and
the budgets (a refresh of the 3-row section with the preview at most 3 s; one tick in Plotted explorations is one
rebuild and no type scan); `test_migration_v6.py` the version 6 migration (one layer becomes the first row, the
`as_rows` invariant, an older project opened and refreshed is not rewritten). `test_hover_layers.py` covers the
layer in the hover, the other points in the readout, popup and map, and "+N here" / "Also here". Existing tests
that drove the 0.3.2 single-layer widgets read the first row instead (`fixtures.explo_row`, `model.layer_rows`,
`model.as_rows`), with their values unchanged. `test_realdata_gpkg.py`, with real data and his GeoPackage (read
only: a byte copy is opened, and the original is checked unchanged afterwards; the counts, labels and dates are
checked only while the file's SHA-256 is that of the file they were measured on), builds the three rows on a dense
line (38 + 7 + 1 explorations; TW-2 and D-447 (TW-2) both plotted; D-447's TD 280 ft from WellCompleteDepth; epoch
dates), compares the type totals with a GROUP BY on the file, and, through the panel on a fresh project: the
guessed rows, D-447 stopping at the frame with its arrow and TD on the sheet, an exploration left off kept through
a project save and reload and left out of the points CSV, a PDF of the three rows with every label and no layer
legend (all black), and the panel's budgets.

0.3.4 (decision 23). Layers drawn in Color always get a fixed renderer (`fixtures.single_renderer`,
`categorized_renderer`, `rule_renderer`; `TYPE_CATS`, and `CUMBERLAND_AESI`, his Cumberland style as a literal;
`color_model` makes a hand-made model's row Color). `test_symbology.py` covers `symbol_color` (fill, white or
transparent fill and unfilled shapes to the outline, the 230 threshold, symbol layers in order, a disabled layer,
data-defined colours per feature), `layer_style` (single, the 13 Cumberland categories in order, an unticked
category, graduated ranges, nested rules with an ELSE and an inactive rule, displacement and cluster unwrapped,
heatmap or no renderer: none), `read_styles` per fid (the probe's NULL + "" categories drawn with the later "",
out-of-range values, overlapping rules taking the last, a feature matched only by an unticked rule not taken by
ELSE, a scale-ranged rule at scale 0, data-defined size legends left out, only the requested fids, the layer's own
renderer never started), the build's Color rows (plotted and left-off hits stamped, Black and Gray rows never read
the style, a style that cannot be read: black with the warning) and the 3-row budget with a row in Color.
`test_migration_v7.py` covers the new Settings keys and their defaults, `grid_spec`, `depth_widths`,
`clean_sheet_style` through `from_json` and `settings_store.load`, the v7 step (By type rows to Color, the key
gone, idempotent, `bytype.json` to one Color row, the store agreeing) and a v6 Color row losing its `color` key.
`test_render_layers.py` (`ColorLayers`) the Color lines, bars, arrow and black ink, the legend rules (categories in
legend order, merged and repeated labels, two Color rows of one style listing each colour once, single symbol by
the row name, black-only and no-depth-line rows, z-free entries, margins) and the depth widths from Sheet style;
`test_export.py` (`CustomGrid`) the absolute dash and dot patterns at two widths, the SVG dash arrays and a 300 dpi
PDF raster whose frame still measures exactly.
`test_sheet_style.py` covers the Sheet style group (the mockup's order and texts, Custom shown only under Custom,
the first Custom from the preset in use and his values kept through Green and Gray and a project reload, Start
from in one save and one rebuild, the line-style icons, the spins and Reset, the NEW badge, the chip's states,
nothing written to QgsSettings, round trips and stored values clamped, the spacing note);
`test_point_rows.py` (`StyleBox`) the row's style box for every kind, chips, "+ N more", the switched-off note and
the header swatch; `test_panel_layers.py` (`StyleFollow`) the dock following `styleChanged` (box refreshed and a
rebuild for a visible Color row only, nothing saved, no re-track on a look change, a layer already watched for
another row, cleanup). The strip: `test_preview_tools.py` (`CompactStripTest`: the 45 px row, one row of equal
tiles in a 700 px preview, wrapping only when the numbers do not fit (the ground and 10 surfaces: 12 tiles in
one row without a screen, 8 a line in Segoe UI 9 pt with MW-2's screen), numbers never cut and names, labels and
details cut, the kept " · off view" / " · +N here", the navy distance, "Ground"; `RealDataStripTest`: his CDF
section with six CDF_Mounding surfaces, 8 tiles in one row at 700 px, no fallback) and `test_hover_csv.py`
(`StripCellsTest`). `test_compat_032.py` gives its explorations a frozen categorized renderer, made the bytype case
again once (`remake_case`, `XSECTIONS_REMAKE_GOLDEN=bytype`, `REMADE`; plan unchanged, the two sheets new) and checks
its sheets carry the Boring and Monitoring Well colours (`test_bytype_takes_the_layer_style`); the other four cases
are still pixel-identical. `test_realdata_gpkg.py` adds, on the byte copy, AESI in Color with his Cumberland style
(every hit its category's colour read by fid with sqlite, NULL or unmatched values in the catch-all), a Tehaleh-like
rule-based variant (two rules on, the rest and ELSE off), the 3-row budget with AESI in Color, the Color legend on
the sheet and in a PDF (categories in Cumberland order, names and ticks black), and the panel's style box
("Categorized by ExploType · 13 categories", 4 chips, "+ 9 more", following a category switched off).

0.3.5 (decision 24). `test_text_numbers.py` writes real CSV files to the run's temp folder and opens them with
the `ogr` provider: his Boring Summary's columns (every field a String, asserted; 0.3.4's numeric-only box lists
none), the row's Water level box listing them, opening and set by a click, kept on a reload; the guesses (GW Elev.
(ft) for elevations, DTW for depths, a saved field it lacks guessed again; a level column that matches no name
leaves the box empty, never the name column, and the build asks for it; a text column guessed only when it holds
numbers: CDF_wells' Elevation_ is not, a mixed table's "GW Elev. (ft)" is), every number box's filter; the build
reading the table's levels (spaces trimmed, 5e2, no Kind column = ATD), the empty cell not counted and the three
texts left out with one warning, once for two rows, its own for another field, the 1-level wording, zero is
missing unchanged; a `.csvt` and a GeoPackage table as before; an exploration row and an Other points row on a CSV
point layer (X and Y columns) with tops, depths, levels and elevations from text and their flags; his steps in the
dock. The pure part: `text_number` on good and bad texts, the name matching, number fields first, dates kept out.
`test_text_numbers.ScreensAre` checks Elevations | Depths with the stored values and the default unchanged.
Edited for the change: `test_panel` (the screen_values order), `test_ui` (the depth boxes' filter),
`test_point_rows` (`test_set_field`: a number box keeps a text field; `test_water_rules`: a text DepthToGW is
guessed when no number field matches). `test_realdata_gpkg.test_budgets` first deletes what earlier tests gave to
`deleteLater` (`sendPostedEvents(None, DeferredDelete)`), so that flood no longer falls inside its timed wait.
`test_orientation.py` (decision 25): `plan()` with each orientation on a short section (Letter landscape in Auto;
Portrait gives Letter 8.5 × 11 at the same plot size), a tall one (Letter portrait in Auto; Landscape goes to Tabloid
landscape), named sheets, fill with grid on the page it gets (2 majors landscape, 4 portrait), the compact layout,
a long section tiled (Auto 4 Tabloid landscape; Portrait 8 Tabloid portrait sheets, whole-major cores, one major of
overlap, cores covering the section), the no-fit messages (Auto's word for word; "in portrait. Choose Auto or
Landscape, …" only when the other one would do; the tiling height message with only the chosen room; the coarse
grid), a custom page and unknown values unaffected, a page Auto gives landscape (portrait) identical with
Landscape (Portrait); the setting (default, place after `sheet`, JSON and project round trips, a bad value ->
"auto", older settings -> Auto, version 7); the panel control (order, data, tooltips, default Auto, the row right
under Sheet | Format at full width at 340 and 260 px, disabled with its tooltip for Custom, saved and restored, a
click starting the debounced rebuild and the real pipeline giving portrait and tiled portrait sheets, readout and
chip naming the sheet); PDF page boxes (and a PNG's pixels) in the chosen orientation, tiled pages too. Auto is
checked by the untouched golden / compat tests (`test_compat_032`, `test_scales`).
`test_explorations.ProjectionDirection` (decision 26): three lines in one layer (east-west, north-south,
north-west to south-east) and seven wells: a well north of the east-west line reads "S" (south of it "N"), east of
the north-south line "W" (west "E"), north-east of the third "SW" (south-west "NE"), one on the line "" with
offset 0; side unchanged; the same wells as other points give the same; the labels ("N-1 · 40 ft S", "E-2 · 30 ft
W", "NE-3 · 50 ft SW", "ON-1 · 0 ft"), the points CSV's direction column and the notes (standard and compact
texts). Edited for the change (each with a
comment): `test_explorations.test_station_offset_side_direction` (the reverse of the side's normal; B-1 "S", MW-1
"N"), `test_other_points_core` (S-1 "S", S-2 "N"), `test_figure.test_display_label` ("B-1 · 35 ft S"),
`test_scales.test_headroom_grows_for_long_labels` ("MW-12R · 140 ft SE"), `test_layout` (the compact notes text),
`test_compat_032` (`REMADE` manual, `NEW_DIRECTIONS`, `OPPOSITE` and `_hits_golden`, the remake writing only the
direction values and a changed plan, and `test_manual_directions_are_projections`: manual's directions are the
reverse of basic's, every other value equal).

0.3.6 (decision 27). `test_symbols.py` covers the catalogue (the drop-down's groups, order, names and usual colours,
the asterisk heading General shapes, the star legacy and never offered), 0.3.5's six shapes kept exactly (frozen
copies of their 0.3.5 code compared), unknown keys (cleaned on load to the kind's default, drawn as the circle),
every new symbol's geometry and footprint, resting on the ground line (on the drawn artists), the benchmark centred,
the spring's tail downhill (and right on flat ground), the artists, the legend fit and the preview's cost;
`test_symbol_icons.py` every icon at 22 × 16 and at device pixel ratio 2, theme-independent, from the same geometry,
and the bracket mark (solid and dashed, its ticks solid). `test_other_features.py` covers the four row keys (a 0.3.5
row loads as itself, `feature_row`, no version step), the kinds, the crossings (each one, touches, the ends, a stretch
along the line and a short one, one stream split at the line, the placement rules, a missing field, another CRS),
the pieces (every area, open ends, blank labels, types and a bow tie, A on a polygon's edge in another CRS), the
build (a row of each kind, the layer deciding the kind, a missing polygon layer, the hover) and a budget (2,000 lines
and 5,000 polygons, 20 of each on the line, built in 1.5 s); `test_other_features_render.py` the crossings on
the sheet, the brackets inside the frame (over the ground and the labels, stacking, edge lines that stop at labels),
Auto and Manual ranges (lowered with the warning, none lost under a manual minimum), above the frame (the band, the
margins, the furniture moved up, tiles, edge lines that stop at the frame), the legend swatches, the preview laying
the brackets out at its own scale, and sheets without line or polygon rows drawn as before. The panel:
`test_panel_widgets.py` (the visual system on its own: the light and dark tokens, the tile and bar and their count
chip, the body on its rail, the Flare band's pixels and the cards' spacing, the whole-card click, subsections and
field names, pairs and check-box grids that stack, the painted dashed boxes, Verbose and its hints, which leave no
hub connection behind, the tabs, the badge, card and host with the 100 ms rule, the swatches, the stylesheet),
`test_feature_rows.py` (the rows: the three kinds and their editors, the symbol drop-down whose headers are never
picked, subtitles and icons, the tabs, the guesses and Looks right, problems on a row, Plotted, the lists' spacing
and bands) and `test_panel_036.py` (the dock: the six sections and every moved control and text, Manual and the
grid spacing, Verbose in the ⋯ menu, per user and never in the project, the problems, count chips and the check card
from the dock, the status line, the bands, Other features rows of three kinds from the dock, and nothing cut at
260 and 340 px in light and dark). Verbose is only ever written in the test profile `start_app` makes; a test that
turns it on turns it off again (`addCleanup`). Existing tests were edited for the new texts and places only (names in
sentence case, the shorter texts, Verbose turned on before a hint or readout is read, the six sections, the tabs
instead of More, "Other features", `guessed` in the rows' key lists), each with its reason in the build reports.
