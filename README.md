# XSections

A QGIS 4 plugin for geologic cross sections at exact scale. Draw or pick a section line; XSections
samples a LIDAR DEM along it, projects nearby explorations (borings, wells, CPTs, test pits) onto it,
and exports sheets you can measure with an engineer's scale and draw on by hand.

---

## For users

### What it does

- **Ground line** from your LIDAR DEM, with gaps where the DEM has no data.
- **Explorations** within a tolerance of the line, filtered by type: each gets a **tick and its name
  just above the LIDAR ground** at its station.
- **Optional top-to-bottom line** for each exploration: the top from your table, or LIDAR where the
  table has none (or a zero, or a value far from LIDAR); the bottom from a bottom-elevation field, or
  the top minus the total depth. A **short bar marks the top** when it is off the ground line, and each
  line can be labelled with its total depth under the bottom, **TD 50'**.
- **Explorations are optional:** a line and a DEM alone give a ground-only section.
- **Other surfaces:** any number of rasters (water-level surfaces, MODFLOW layer tops and bottoms) drawn
  as lines in your own colour, style and width, smooth or flat across each model cell.
- **MODFLOW 6 models:** the model top, layer bottoms, heads for a chosen layer and stress period, and the
  water table, read straight from a run folder (DISV, DIS or DISU).
- **Screens and water levels:** a bracket for each well screen; the measured water level as an open blue
  triangle joined to the middle of the screen; water seen at the time of drilling (ATD) as filled blue
  triangles, several per boring if you have them; optional elevation and date labels.
- **Exact-scale PDF, PNG or SVG** with **separate horizontal and vertical scales**
  (for example 1 in = 100 ft H, 1 in = 10 ft V), a **major and minor grid** and graphic scales.
  Nothing is ever shrunk to fit.
- **Letter and Tabloid tiling:** a long section is split across sheets with match lines.
- A panel with live readouts, a preview, and highlights on the map.

### Requirements

- **QGIS 4.2 or newer** (tested with 4.2.1). Older QGIS versions show the plugin as incompatible; upgrade QGIS first.
- numpy and matplotlib. **They are included with the standard Windows installers** (the standalone
  installer, and OSGeo4W Express or its *qgis-full* package), so there is usually nothing else to
  install. An OSGeo4W Advanced Install of just the *qgis* package needs *python3-matplotlib* added.
  If they are missing, XSections shows a message saying how to add them.
- A **DEM** (the panel waits for one before it draws anything) and, usually, a **point layer of
  explorations**. Without explorations you get the ground line only.

### Install (from a ZIP file)

1. Get `xsections-<version>.zip`: sent to you, or from the project's **GitHub Releases** page,
   under *Assets*. Download the file named `xsections-<version>.zip`, **not** *Source code (zip)* or
   *Source code (tar.gz)*: QGIS accepts those but the plugin never loads. (If the repository is
   private, you need access to it first.) Do not unzip it.
2. In QGIS: **Plugins > Manage and Install Plugins…**
3. Open the **Install from ZIP** tab, click **…**, and choose the zip.
4. Click **Install Plugin**. If QGIS warns about installing from an untrusted source, click **Yes**.
5. QGIS reports *Plugin installed successfully*. Close the dialog.

The **XSections** button (a small ground profile with red ticks) is on the **Plugins toolbar**
(*View > Toolbars > Plugins Toolbar* if you don't see it), and in the menu
**Plugins > XSections > XSections**. It opens the panel on the right and the preview at the bottom.

### Quick start

1. Add your **LIDAR DEM** and your **explorations** point layer (optional: without it you get a
   ground-only section) to a project in a projected CRS (for example WA State Plane South, US feet). If
   QGIS asks which transformation to use for a layer, accept the default.
2. Click the **XSections** button. The panel opens with every section closed; the header of each says
   what is set, and an amber one says what is still missing. Click a header to open it.
3. **Line:** choose a line layer and feature, or click **Draw** (click the vertices, right-click to
   finish). **⇄** (Reverse) swaps the ends; the end labels default to A and A′.
4. **Surfaces:** the ground row holds the DEM (check *More: units and datum* for the **vertical datum**,
   NAVD88 unless you change it; it is printed on the sheet). Add other rasters with **+ Add surface**.
5. **Explorations:** choose the point layer, the label and type fields, tick the types to show, and set
   the tolerance (ft).
6. **Depths:** the line from top to bottom is on by default. Check the **Top elevation**, **Bottom
   elevation** and **Total depth** fields it guessed from the field names (leave any of them empty if your
   table does not have it), and whether to **label the total depth** (TD 50'). The readout says where each
   top and bottom came from.
7. **Screens & water** (optional): the screen fields, whether water levels are elevations or depths, and
   the water level fields (see below).
8. **Scale & sheet:** set *Horizontal 1 in = … ft* and *Vertical 1 in = … ft*, check the sheet and tile
   readout, then click **Export…** and choose PDF, PNG or SVG. *Sheet style* sets the grid colour, data
   line colours, printer edge, grid fill, and whether bends get a dashed line (see *More room to draw*).
   **⋯** next to Export has *Export points CSV…* and *Save line to layer*.

Settings are saved in the QGIS project; your own layers are only read, never edited. Projects saved
with an earlier version keep their settings (0.1.x projects get no surfaces, screens or water levels until
you set them up).
**Save line to layer** puts a drawn line in a temporary layer: right-click it > *Make Permanent* to keep it.

### More room to draw (Sheet style)

The scales fix the size of the drawing: the plot is always exactly (length ÷ horizontal scale) ×
(elevation range ÷ vertical scale). These options decide how much of the paper around it is left free, and
whether the grid grows to use it.

**The defaults (since 0.1.2):** the **compact layout** with the **grid filled below the section**, a **0.5 in**
printer edge and the **notes on**. Projects saved with 0.1.1 keep the layout they had; projects from 0.1.0 get
the new defaults. Change any of them here.

- **Compact layout (more room to draw)**, on by default: the title on one line, the end letters (A (S),
  A′ (N)) just above the frame, two short note lines (5.5 to 6 pt) beside the horizontal scale bar, and the
  elevation title on the left only. On Letter landscape the room for grid grows from 8.5 × 5.0 in to about
  8.9 × 6.5 in. When the notes need the room, the scale bar moves left of the plot; on a narrow sheet
  (Letter portrait) the least needed parts, such as the sheet name and the depth sources, are left out
  (the explanation of TD labels and label offsets always stays). Untick it for the standard layout: the title
  on two lines over the plot and the full notes under it.
- **Printer edge:** *0.5 in (any printer)*, the default, or *0.3 in (most laser printers)*: the clear strip
  kept at the paper edge; every margin moves with it (about 9.3 × 6.9 in of room on Letter landscape,
  compact). **0.3 in suits most laser printers:** most office laser printers print to within 0.25 in of the
  edge; inkjets and some copiers need more. To check yours, print a 0.3 in sheet at actual size: if any line,
  letter or number is cut off at the edge, use 0.5 in.
- **Show notes under the section**, on by default: untick to leave the notes off (the grid, graphic scales,
  axis labels and title stay). In the standard layout this frees about 1 in at the bottom.
- **Fill the sheet with grid:** *Below the section* (the default), *Above and below* (the larger half below,
  where the geology goes) or *Off*: adds whole major grid intervals (1 in with the default grid) to use the
  sheet height. The first three options only make room; this one turns it into grid. Not used with a custom
  page size, or when *Elevations* is *Manual*: the sheet then shows the range you typed (rounded to the major
  grid).

### The panel

The sections follow the drawing from the top down: **Line**, **Surfaces**, **Explorations**, **Depths**,
**Screens & water**, **Scale & sheet** and **Sheet style**. They are all closed when the panel opens; each
header shows what is set (for example *A–A′ · 1,534 ft*) or, in amber, what is still missing (*Choose a
DEM*). Open as many as you like. Settings you rarely change are under **More** inside their section.

### Other surfaces

Under **Surfaces**, the ground (your LIDAR DEM) is always the first line. **+ Add surface** adds another
raster: a water-level surface, a MODFLOW layer top or bottom, anything with elevations. Click a surface's
name to set it up:

- **Raster** and **band**, a **name** for the legend (the layer name if left empty), and its **colour**
  (the swatch), **line** style (solid, dash, dot) and width.
- **Draw as:** *Smooth* (the default; interpolated between cell centres, like the ground) or *Cells* (flat
  across each cell with a step at each cell edge, so a model layer shows its grid).
- **Include in the elevation range:** on by default. A deep model bottom makes the sheet taller (every
  20 ft is another inch at 1 in = 20 ft, and sections never split vertically); untick it to clip that line
  at the frame instead.
- **▽ marks along the line:** water-table triangles every 2 in of paper (they step aside for the
  explorations).
- **Units:** as for the DEM (*Auto* reads them from the layer).

**+ Add all bands…** adds one surface per band of a multi-band raster. The tick box beside a surface hides
it without losing its settings; the **⋯** button moves it up or down or removes it. A surface whose raster
is missing is left out with a note; it never stops the section. Surfaces are listed in the legend and the
notes.

### MODFLOW 6 surfaces

Under **Surfaces**, **+ Add MODFLOW 6…** reads a MODFLOW 6 model straight from its run folder (no flopy or
other installs needed). Pick the folder (or a name, grid or head file); the dialog shows the model's grid (DISV,
DIS or DISU), layers, units and saved head times. Tick what to draw:

- **Model top** and **layer bottoms** (one tick per layer).
- **Heads** for any layer, at the **time** you choose: *Last saved* (the default), a stress period (its last saved
  time step), or a particular step.
- **Water table**: the head of the uppermost wet layer at each cell.

Set the **model CRS** (the project CRS unless the model coordinates are in another one) and *Smooth* or *Cells*,
then **Add**. Each becomes a surface you can restyle like any other; its editor also changes the layer, the time or
the model. Dry and inactive cells leave a gap. Re-running the model updates the section the next time it is drawn.
Elevations are converted from the model's LENGTH_UNITS.

### Screens and water levels

Under **Screens & water**:

- **Screen top** and **Screen bottom** fields, as **depths** below the exploration's top (the same top the
  depth line uses) or as **elevations**. The screen is drawn as a bracket just left of the exploration line.
- **Water levels are:** *Elevations* or *Depths below the top* (the same top as the screens and the depth
  line; a negative depth is above it). One switch for the measured field, the ATD field and the table.
- **Water level (measured)** and its date. Drawn as an open blue triangle, tip on the
  level, with a short black line under it, on a black leader from the middle of the screen bracket that
  runs out to the left and up (or down) to the level. Without a screen it sits just left of the exploration line.
- **Water level (ATD)** and its date: water seen at the time of drilling. Drawn as a
  filled blue triangle just left of the exploration line.
- **Print beside the symbol:** off, the elevation (*652.8*), or the elevation and date (*652.8 (6/12/2025)*).
- **More: water-level table** for several levels per exploration (more than one water-bearing zone): a
  table with one row per level (a CSV or Excel sheet added to QGIS works; it needs no geometry), with the
  exploration name, the water level, and optionally a date and a kind. Names are matched to the label field,
  ignoring case. Rows whose kind contains "ATD" (or the kinds you tick) are ATD levels, the others measured;
  without a kind field every row is ATD.

A screen or water level that cannot be right (entirely above the top or below the bottom of its
exploration) is left out and listed in the panel: check the *Elevations / Depths* switches, since such a value
was most likely entered as the other kind.

### Tops, bottoms and total depth

Each exploration is worked out on its own, from the best data it has:

- **Top:** the *Top elevation* field where it has a value (not empty, and not 0 while *Treat 0 as
  missing* is ticked) that is within 25 ft of LIDAR; otherwise **LIDAR at the exploration** itself.
  A table value that LIDAR contradicts is listed in the panel (for example "ExploElev 205.6 ft ignored:
  469.0 ft from LIDAR"). *Top from* can also use LIDAR only, or the table only.
- **Bottom:** the *Bottom elevation* field where it has a value below the top; otherwise the **top minus
  the total depth**. A bottom elevation at or above the top is ignored and listed. When the table's
  top is used, its bottom elevation is used too; if it is more than 5 ft from top − depth it is listed
  so you can check it. When the top came from LIDAR instead (the table top was ignored as wrong), a
  bottom elevation more than 25 ft from LIDAR top − depth is ignored and listed, since it was most
  likely worked out from the wrong top. When the table top was ignored and there is no depth, the bottom elevation was
  most likely worked out from that wrong top: it is **moved with the top** (LIDAR minus the table's
  top-to-bottom distance) and listed.
- **TD label:** the total depth field, or top − bottom when the table has no depth.
- **Units:** table elevations and depths are read as **feet**. A top that only makes sense in meters
  is flagged ("205.6 m would match").

Typical tables: *depth only* (tops from LIDAR, bottoms from top − depth), *top elevation and depth*
(the usual case), or *top and bottom elevations*. The notes under the section say which fields were
used. **Export points CSV** lists each exploration with its top and bottom sources.

### Printing at scale

The PDF asks viewers to print at actual size, but always check the print dialog:

| Viewer | Setting |
|---|---|
| Adobe Acrobat / Reader | Page Sizing & Handling: **Actual size** |
| Chrome or Edge | More settings > Scale: **Default** (or *Actual size*), never a *Fit* option |
| Firefox | Scale: **100%** (not *Fit to page width*) |

Use paper of the sheet's size (Letter 8.5 × 11 or Tabloid 11 × 17). Then **check the print with your
engineer's scale on the grid**: with the default grid, major lines are exactly 1 inch apart.

### Update and uninstall

- **Update:** install the newer zip the same way (*Install from ZIP*). It replaces the old version in
  place (same plugin, `xsections`); the version number shows in the Plugin Manager. Your settings,
  which are saved in each QGIS project, carry over. Restart QGIS if the panel misbehaves afterwards.
- **Uninstall:** *Plugins > Manage and Install Plugins… > Installed*, select **XSections**, click
  **Uninstall Plugin**. Settings stored in your projects stay there and are simply ignored.

---

## For developers

The design and the drawing spec are in [docs/DESIGN.md](docs/DESIGN.md).

### Layout

```
xsections/          the plugin folder (what the zip contains)
  core/             geometry and data: units, DEM sampling, projecting explorations, build_section
  render/           sheets: page planning, drawing, PDF/PNG/SVG export, PDF print preferences
  ui/               the dock, map tools, preview, map highlights, settings storage
tests/              unittest suite (headless) and pixel measurement helpers
scripts/            run_tests.bat, package.py/.bat, install_dev.bat, uninstall_dev.bat
.github/workflows/  build.yml (zip on every push), release.yml (GitHub Release on a v* tag)
```

### Run the tests (Windows, OSGeo4W QGIS 4)

```bat
scripts\run_tests.bat                      :: everything (headless, about 5 minutes)
scripts\run_tests.bat tests.test_export    :: one module
```

They run QGIS's own Python (`python-qgis.bat`) offscreen. Export tests measure the files from their
pixels. Real-data tests run only when `XSECTIONS_REALDATA` points at a folder with copies of
`CDF_wells.shp` and `cdf_lidar.tif` (they are copied again before use, so nothing is written there).

### Build the zip

```bat
scripts\package.bat                        :: or: python scripts/package.py (any Python 3.9+)
```

This writes `dist\xsections-<version>.zip` (version from `xsections/metadata.txt`) with one top
folder, `xsections/`, which QGIS uses as the plugin id. Tests, bytecode and editor files are left out,
and the zip is rejected if any file contains an absolute or user-specific path.

### Develop against a live QGIS

`scripts\install_dev.bat` links `%APPDATA%\QGIS\QGIS4\profiles\default\python\plugins\xsections`
to this repo's `xsections` folder (a directory junction; no admin rights) and refuses if something
of that name is already there. Enable **XSections** under *Plugins > Manage and Install Plugins >
Installed*; restart QGIS (or use Plugin Reloader) after code changes. `scripts\uninstall_dev.bat`
removes only the link. Uninstall a zip-installed copy before linking, and vice versa.

### Make a release

1. Bump `version=` in `xsections/metadata.txt` and add a line under `changelog=`.
2. Run the tests, commit, and tag the commit `vX.Y.Z` (the same version): `git tag v0.2.0`.
3. Push the tag: `git push origin v0.2.0`.

`release.yml` builds the zip and creates the GitHub Release with it attached; it fails if the tag
and `metadata.txt` disagree. `build.yml` builds the zip on every push and pull request and keeps it
as a workflow artifact (GitHub wraps it in another zip; unzip once before installing).

CI does not run the QGIS tests: they need a full QGIS 4 (PyQt6, GDAL, a Qt GUI application run
offscreen), which GitHub's runners don't have. Run `scripts\run_tests.bat` before tagging.

---

## License

XSections is free software, licensed under the **GNU General Public License, version 2 (GPL-2.0)**.
See [LICENSE](LICENSE). The plugin zip includes the same file.
