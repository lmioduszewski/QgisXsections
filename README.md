# XSections

A QGIS 4 plugin for geologic cross sections at exact scale. Draw or pick a section line; XSections
samples a LIDAR DEM along it, projects nearby explorations (borings, wells, CPTs, test pits) onto it,
and exports sheets you can measure with an engineer's scale and draw on by hand.

---

## For users

### What it does

- **Ground line** from your LIDAR DEM, with gaps where the DEM has no data.
- **Explorations** from one or more point layers (your own explorations, explorations by others, supply
  wells), within a tolerance of the line and filtered by type: each gets a **tick and its name just above
  the LIDAR ground** at its station. Every layer is drawn in black like your own, unless you set it apart in
  gray, or in colour from the layer's own QGIS style; you can leave single explorations off a section.
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
- **Other points** such as seeps or springs: a symbol (a bold blue 8-pronged asterisk by default) with its
  name, resting on the ground line, or at the LIDAR or an elevation from the attribute table.
- **Exact-scale PDF, PNG or SVG** with **separate horizontal and vertical scales**
  (for example 1 in = 100 ft H, 1 in = 10 ft V), a **major and minor grid** (green, gray or your own colours,
  widths and line styles) and graphic scales. Nothing is ever shrunk to fit.
- **Letter and Tabloid tiling:** a long section is split across sheets with match lines. Sheets are
  landscape or portrait as fits best, or all one way if you choose.
- A panel with live readouts, highlights on the map, and a **preview** you can zoom and read by hovering,
  with the elevation of every surface under the mouse; the surfaces export to CSV.

### Requirements

- **QGIS 4.2 or newer** (tested with 4.2.1). Older QGIS versions show the plugin as incompatible; upgrade QGIS first.
- numpy and matplotlib. **They are included with the standard Windows installers** (the standalone
  installer, and OSGeo4W Express or its *qgis-full* package), so there is usually nothing else to
  install. An OSGeo4W Advanced Install of just the *qgis* package needs *python3-matplotlib* added.
  If they are missing, XSections shows a message saying how to add them.
- A **DEM** (the panel waits for one before it draws anything) and, usually, one or more **point layers
  of explorations**. Without explorations you get the ground line only.

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

1. Add your **LIDAR DEM** and your **explorations** point layers (optional: without them you get a
   ground-only section) to a project in a projected CRS (for example WA State Plane South, US feet). If
   QGIS asks which transformation to use for a layer, accept the default.
2. Click the **XSections** button. The panel opens with every section closed; the header of each says
   what is set, and an amber one says what is still missing. Click a header to open it.
3. **Line:** choose a line layer and feature, or click **Draw** (click the vertices, right-click to
   finish). **⇄** (Reverse) swaps the ends; the end labels default to A and A′.
4. **Surfaces:** the ground row holds the DEM (check *More: units and datum* for the **vertical datum**,
   NAVD88 unless you change it; it is printed on the sheet). Add other rasters with **+ Add surface**.
5. **Explorations:** one row per point layer (see *Several exploration layers* below). A new project gets
   a row for each layer named like explorations, with its fields guessed from the field names; click a
   row to check its label and type fields and tick the types to show, and **+ Add point layer** for
   another. Set the tolerance (*Within*, ft), which every layer shares. **Plotted explorations** lists
   what is on the section; untick one to leave it off.
6. **Depths:** the line from top to bottom is on by default. The **Top elevation**, **Bottom elevation**
   and **Total depth** fields are in each layer's row, under *More: depths, water and range* (guessed from
   the field names; leave any of them empty if your table does not have it). Choose whether to **label
   the total depth** (TD 50′). The readout says where each top and bottom came from.
7. **Screens & water** (optional): screens and water levels on or off, and the label beside the symbol;
   their fields are in each layer's row too (see below).
8. **Other points** (optional): **+ Add point layer** for seeps, springs or other points (see below).
9. **Scale & sheet:** set *Horizontal 1 in = … ft* and *Vertical 1 in = … ft*, choose the *Sheet* and its
   **Orientation**: *Auto* (the default, as before 0.3.5) takes each sheet landscape when the section fits,
   else portrait; *Landscape* or *Portrait* puts every sheet that way, tiled sheets too (a long section then
   tiles on portrait sheets). A custom page size is sized to the drawing, so Orientation is off for it. When
   nothing fits, the message names the orientation and says when *Auto* or the other one would do. Check
   the sheet and tile readout, then click **Export…** and choose PDF, PNG or SVG. *Sheet style* sets the
   grid (Green, Gray or your own colours, widths and line styles), the depth line widths, printer edge, grid
   fill, and whether bends get a dashed line (see *More room to draw*).
   **⋯** next to Export has *Export points CSV…* and *Save line to layer*.

Settings are saved in the QGIS project; your own layers are only read, never edited. Projects saved
with an earlier version keep their settings (0.1.x projects get no surfaces, screens or water levels until
you set them up; a project from 0.3.2 or earlier opens with its explorations layer as the first row, with
the same fields, types and table of water levels, and looks exactly as before). A project that used *Data
lines: By type* (0.3.3 and earlier) opens with those layers in *Color*, so their lines take the colours of
the layer's own QGIS style instead of the plugin's type colours; a 0.3.3 layer drawn in a colour you picked
is in *Color* from its layer style too.
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
  on two lines over the plot and the full notes under it (the space under the plot grows when long notes and
  a long legend need it, so they never run into the printer edge).
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

Sheet style also sets how the grid and the depth lines look:

- **Grid:** *Green* (the default engineering pad: major lines 0.7 pt, minor 0.35 pt, solid), *Gray* (for
  black-and-white printers, the same widths) or *Custom*, your own **color**, **width** (0.1 to 3 pt) and
  **line** (solid, dashed or dotted) for the major and the minor lines. Under Green or Gray a line shows the
  preset's colours and widths. The first time you choose Custom it starts from the grid you had; *Start from
  Green · Gray* starts it again from a preset. Clicking Green goes back to the default at once, and Custom
  keeps your settings for when you come back. Dashes are the same length at every width: dashed 4 pt on,
  2 pt off; dotted 0.6 pt dots 1.6 pt apart, with round ends (a dotted line 1.6 pt or wider reads as solid).
  A custom grid is saved with the project only (a new project starts on Green), and the preview draws it
  as the sheet does. The frame around the plot stays 0.9 pt black whatever the grid, and the spacing
  (major lines every inch, minor every tenth with the automatic grid) is still set under *Scale & sheet*.
- **Depth lines** (new in 0.3.4): the width of the lines from top to bottom, *Black and gray* (0.75 pt by
  default, 0.25 to 3 pt) and *Color* (1.6 pt by default, so pale colours still show; 0.25 to 4 pt), in steps
  of 0.05 pt; **Reset** goes back to 0.75 and 1.6 pt. The bars at the bottom and the top follow the line,
  and the legend's swatches are drawn at the same widths. Which layers are black, gray or in color is set
  for each layer, under *Explorations > Drawn in*. (With the line from top to bottom off, under *Depths*,
  the widths are disabled.)

### The panel

The sections follow the drawing from the top down: **Line**, **Surfaces**, **Explorations**, **Depths**,
**Screens & water**, **Other points**, **Scale & sheet** and **Sheet style**. They are all closed when the
panel opens; each header shows what is set (for example *A–A′ · 1,534 ft*, or *2 of 3 on · 46 plotted*)
or, in amber, what is still missing (*Choose a DEM*, *Layer missing*). Open as many as you like. Settings
you rarely change are under **More** inside their section.

### Several exploration layers

**Explorations** is a list of point layers: your own explorations, explorations by others, supply wells,
and so on (where their lines cross, the first row is drawn on top). A new project gets a row for each
layer named like explorations (up to six; supply wells last, and unticked: tick them on when you want
them), with every field guessed from the field names (never the GeoPackage `id` column). **+ Add point
layer** adds a row. The tick box beside a row leaves the layer off without losing its settings; its **⋯**
button moves it up or down or removes it. The header shows the legend name and a summary (layer · label
field · types · how many are plotted). Click a row's name to set it up:

- **Layer** and a **Legend name** (the layer name if left empty).
- **Drawn in:** *Black* (the default, like your own explorations), *Gray* to set a layer apart (its depth
  lines, ticks, names and TDs in gray), or *Color*: each exploration takes its color from the layer's own
  style in QGIS (*Layer Properties > Symbology*), whatever it is (one symbol, categories, ranges or rules,
  and a fill colour set from a field), so the sheet matches your map. Only the depth line takes the colour
  (with its bars, top cap, dotted link and the arrow at the frame), drawn at the *Color* width of Sheet
  style; **names, ticks and TDs stay black**. A white or nearly white symbol (a hollow marker) gives its
  outline colour. An exploration the style draws with no symbol (its category or rule switched off in the
  Layers panel, or no rule or range that takes it) is drawn in black, as it is missing on the map. A rule's
  scale range does not matter: the sheet never depends on the map's zoom. For *Color* the row shows what it
  reads, for example *From the layer's style in QGIS: Categorized by ExploType · 13 categories*, the colours
  of up to four of them (those on the section first), *+ 9 more* and how many are switched off; change them
  in *Layer Properties > Symbology* and the sheet follows. In the legend a *Color* layer lists its colours the
  way the layer's own legend names them (the categories, ranges or rules of the explorations drawn on the
  section, in the layer legend's order; one symbol: the layer's legend name; a category that two layers
  share in the same colour, as your own and others' explorations in one style, is listed once); *Black* and
  *Gray* layers are listed by name only when the layers are drawn differently from each other. Screens and
  water-level triangles look the same in every layer.
- **Label field**, **Type field** and the **Types** to plot, each with *plotted / in the layer*;
  **(no value)** is the explorations whose type is empty. *All* · *None* tick or untick them all.
- **More: depths, water and range:** the top elevation, bottom elevation and total depth fields, with
  *In elevation range* beside the total depth; the measured level and its date, the ATD level and its date,
  *Levels are* Elevations | Depths, the screen top and bottom, *Screens are* Elevations | Depths, and
  *Water levels from a table (CSV, Excel…)* (see *Screens and water levels*).
  A note says which fields were guessed, so you can check them. The number boxes list number fields and text
  fields (a CSV added to QGIS has only text fields; the box's icons show which is which): see *Numbers stored
  as text* below.
- **In elevation range** (beside *Total depth*): on for your explorations; off to begin with for supply
  wells (a layer named "supply", or with a *WellCompleteDepth* field). A layer left out never makes the
  sheet taller: its explorations that reach below the bottom of the frame stop there with a small arrow, and
  their TD beside it (shown even with TD labels off: it is the only depth on the sheet); shorter ones are
  drawn whole, their TD under the bar or, where that is crowded, beside the line (or left out, with a note,
  when even that would cover another label). The Explorations readout names them, in amber (*HW-1 runs below
  the frame (TD 254′)*), and says when one's screen or water level is below the frame, where it is not
  drawn, also for a well drawn without a line down there (*SW-1: water level below the frame*). The legend
  and the notes list only the levels and screens that are drawn.

Shared by every layer: the *Within* distance, *Labels* and *Label text*, the top rule (*Top from* and its
25 ft check), *Treat 0 as missing*, TD labels, screens and water levels on or off, and the water-level
label. Dates stored as numbers (milliseconds since 1970, as some GeoPackages keep them) are shown as dates.
With *Label text* set to *Name + offset and direction*, each exploration (and each other point) is labelled
with how far and which way it was projected onto the section line: a well 40 ft north of an east-west line reads
*MW-3 · 40 ft S* (projected 40 ft south onto the line; before 0.3.5 the direction pointed from the line to the
well, *N*). An exploration on the line reads *0 ft*, with no direction.
A row whose layer is no longer in the project turns amber and keeps every setting it had; the section
waits until you choose the layer again, untick the row or remove it. The same layer added again under its
name is taken back by itself, with everything you set (also when the project was opened while the file was
moved or offline).

### Plotted explorations

Everything the rows choose is plotted, even two explorations of different layers a foot apart.
**Plotted explorations (N of M, K left off by you)**, under the rows, lists them by layer, in order along
the line, each with its distance and offset (*300 ft · 40 ft L*). **Untick one to leave it off this
section:** the sheet, the points CSV and the map highlights leave it out. What you leave off is saved with
the project for that section line (another line has its own; *Reverse* and *Save line to layer* keep it;
so does removing a layer, of explorations or of section lines, and adding it again under the same name),
and it stays left off when the list is rebuilt, as long as the exploration is still chosen. **Show all**
plots them all again.

### Other points

**Other points** draws point layers of other features, such as seeps or springs, as a symbol with its name
above it. **+ Add point layer** adds a row (a new project gets one for each layer named like seeps or
springs). Points are chosen by the same *Within* distance as the explorations. A row has the layer, a
legend name, the label field, an optional type field (*none*: every point) with its types, and:

- **Symbol:** asterisk (8 prongs, the default), circle, square, diamond, star or triangle; its **colour**
  (blue by default) and **size** (7 pt).
- **Elevation:** *Ground line* (the default: the symbol sits on the drawn ground line, just touching it,
  on a slope too), *LIDAR at point* (the LIDAR at the point's own location, which can differ from the
  ground line drawn along the section; the centre of the symbol marks it, with a dotted line down from the
  ground line when it is below it), or *From a field* (an elevation in feet; the centre marks it).
  **Where it is empty:** *Line* (on the ground line), *LIDAR* or *Off* (left off, and listed). An
  elevation more than 25 ft from LIDAR is drawn and listed.

The labels are always horizontal and follow *Label text*; they keep clear of the ground line (on a slope
too), of the exploration names and of the other symbols, rising with a leader when they must, and where the
leaders of exploration names run through one, the name is set on white. With a manual elevation range, a
point the range cuts off is left out with its name (the note under the panel says which). Other points are
listed in the legend and the notes and ringed on the map with the explorations; they are not in the points
CSV. A row whose layer is
gone is left out with a note (amber), as a missing surface is; the section is still drawn.

### The preview: hover, zoom and Surfaces CSV

The preview at the bottom of the window shows the whole section as it will print (not to scale on screen).

- **Hover** the section: a guide follows the mouse, and the compact **readout strip above the plot** reads it
  in one row of small tiles: first where you are (*760 ft from A*, or *7+60 from A* with station labels, over
  the elevation under the mouse and its depth below the ground surface, **bgs**, or above it, **ags**), then
  **Ground** and every surface with its elevation and depth. Every tile is the same width and stays put while
  you move, so it is easy to read. A name or a note too long for its tile ends in "…" (the popup shows it
  whole); a number is never cut. The strip is one row (about 45 px tall) even in a dock 700 px wide: a section
  with well screens fits about 8 tiles in a row there, one without screens 11 or more; a second row comes only
  when even the numbers no longer fit. A **popup** next to the mouse shows the same values in a small table.
  A **navy dot** follows along the section line on the map.
- Point at an **exploration** for its top, total depth, screen and water levels (in the strip each water level
  shows its symbol and its date); the map rings it and shows how it was projected onto the line. With more than
  one exploration layer on, the readout and the popup also name its layer. Where explorations of two layers
  sit at the same spot, the readout adds **+1 here** and the popup lists the other one under *Also here*, with
  its layer.
- Point at an **other point** (a seep, say) for its distance and offset, its elevation and where it came
  from (the ground line, the LIDAR at the point or its field), and the LIDAR or the ground line there for
  comparison; the map rings it too.
- Hover the **map** near the section line: the guide moves to that spot on the section, and the first tile
  says how far off the line you are (*50 ft*, *right of the line*; *off view* when the guide is outside the
  zoomed preview).
- **Scroll** over the plot to zoom the whole drawing around the mouse (up to 800 %); drag or Shift+scroll to
  pan; double-click or **Fit** to see it all again. 100 % is the whole section in the panel.
- **Surfaces CSV…** saves the ground and every surface as distance (x) and elevation (y): one row per drawn
  point, or one column per surface every 10 ft (you choose the step). Tick *Also map coordinates* to add
  map x, y.
- The **Readout row** and **Popup** buttons turn each one on or off; both start on and XSections remembers
  your choice. With both off there is no hover guide or map dot.

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

**Screens & water** turns screens and water levels on or off and sets the label beside the symbol. The
fields are chosen for each layer, in its row under **Explorations** (*More: depths, water and range*):

- **Screen top** and **Screen bottom** fields, as **depths** below the exploration's top (the same top the
  depth line uses) or as **elevations** (*Screens are*). The screen is drawn as a bracket just left of the
  exploration line.
- **Levels are:** *Elevations* or *Depths* below the top (the same top as the screens and the depth
  line; a negative depth is above it). One switch for the measured field, the ATD field and the table.
- **Water level (measured)** and its date. Drawn as an open blue triangle, tip on the
  level, with a short black line under it, on a black leader from the middle of the screen bracket that
  runs out to the left and up (or down) to the level. Without a screen it sits just left of the exploration line.
- **Water level (ATD)** and its date: water seen at the time of drilling. Drawn as a
  filled blue triangle just left of the exploration line.
- **Print beside the symbol** (in Screens & water, for every layer): off, the elevation (*652.8*), or the
  elevation and date (*652.8 (6/12/2025)*).
- **Water levels from a table (CSV, Excel…)** for several levels per exploration (more than one
  water-bearing zone): a spreadsheet-style table of water levels with one row per reading (a CSV or Excel
  sheet added to QGIS works; it needs no geometry), with the exploration name, the water level, and
  optionally a date and a kind. Names are matched to the label field, ignoring case. Rows whose kind contains
  "ATD" (or the kinds you tick) are ATD levels, the others measured; without a kind field every row is ATD.
  The *Water level* box lists the table's number and text fields and guesses one by its name (*GW Elev. (ft)*
  for elevations, *DTW* when *Levels are* is *Depths*); a text column is guessed only when it holds numbers.
  When no name fits, the box stays empty and the panel asks you to choose the field.

**Numbers stored as text.** A CSV opened in QGIS reads every column as text (unless a `.csvt` file next to it
gives the column types), so every number box (top, bottom, depth, screens, levels, the table's water level, an
Other points elevation field) also lists text fields. A text is read as a number when it is a plain number,
spaces around it ignored (*642.3*, *-12.5*, *1e3*, and *1,234.5* with commas). An empty cell is no value. Anything else
(*NA*, *dry*, *642.3 ft*) is left out, as an empty value is, and listed in the panel: for the table of water levels
once per field (*Boring Summary: 3 water levels in GW Elev. (ft) are not numbers (left out).*), for an
exploration's own fields beside its name (*B-4: DTW “dry” is not a number: left out*); an Other point with such
an elevation is placed as for an empty one.

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
used (layer by layer when the layers use different fields). **Export points CSV** lists each plotted
exploration with its top and bottom sources and its layer. Its *side* column says where the exploration lies
(L or R, looking from A to A′) and its *direction* column the direction it was projected onto the line, as
on the labels (*S* for a well north of an east-west line; the column kept its name, but before 0.3.5 it held
the reverse, *N*).

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
  core/             geometry and data: units, DEM sampling, projecting explorations and other points,
                    build_section
  render/           sheets: page planning, drawing, PDF/PNG/SVG export, PDF print preferences
  ui/               the dock, map tools, preview, map highlights, settings storage
tests/              unittest suite (headless) and pixel measurement helpers
scripts/            run_tests_parallel.bat/.py, run_tests.bat, package.py/.bat, install_dev.bat,
                    uninstall_dev.bat
.github/workflows/  build.yml (zip on every push), release.yml (GitHub Release on a v* tag)
```

### Run the tests (Windows, OSGeo4W QGIS 4)

```bat
scripts\run_tests_parallel.bat                              :: everything, 6 processes at once (about 3.5 minutes)
scripts\run_tests_parallel.bat tests.test_export tests.test_ui   :: some modules (in parallel when more than one)
scripts\run_tests.bat                                       :: everything in one process (10 to 15 minutes)
scripts\run_tests.bat tests.test_export                     :: one module, one process
```

`run_tests_parallel.bat` runs the same tests as `run_tests.bat`, split over min(6, CPUs - 1) worker
processes (`--workers N` for another number, `--serial` for one process, `--plan` to see who gets what without
running anything). Each worker is a plain `python -m unittest -v` of its share, with its own log in a run folder
under `%TEMP%\xsections_tests` (printed at the start). First one more process lists the tests with unittest's own
loader (a few seconds). The longest modules go first, each to the least-loaded worker, by the times of earlier runs
(`durations.json` in that folder); the few that would hold up the run alone are split into their classes or tests,
but only where the loader's list shows that the parts hold exactly the tests of the whole (tests made at import time
included). At the end every listed test must have started in a worker, or the run fails (`not run=k`). The summary
lists every worker (with its exit status) and module with its time and each failure with its traceback, and ends like
unittest's: `Ran N tests in X s`, then `OK` or `FAILED (...)` (exit status 0 only when everything passed). A worker
passes only when its exit status is the one unittest gives for what it printed: one that prints `OK` and then
crashes (say while QGIS shuts down) fails the run as a crashed worker. Tests with a time limit (the budgets) stretch
their limits and waits by `XSECTIONS_TIME_FACTOR`, which the parallel runner sets to 3 (1 everywhere else, so a
serial run checks them exactly as written); they are tagged `@timing_test` in the source. When several processes
ran, every test that failed is run once more, alone, at the end, and both results are shown: a timing test that
passes alone counts as passed, any other failure stands. A run in one process (`--serial`, `--workers 1` or a single
name) gets no second try: its result stands, as `run_tests.bat`'s would. Ctrl+C ends the workers and removes their
temp folders. Golden files are never made in parallel: with `XSECTIONS_MAKE_GOLDEN` or `XSECTIONS_REMAKE_GOLDEN`
set, the parallel runner refuses (use `run_tests.bat`, with the user's approval).

They run QGIS's own Python (`python-qgis.bat`) offscreen. Export tests measure the files from their
pixels. Real-data tests run only when `XSECTIONS_REALDATA` points at a folder with copies of
`CDF_wells.shp` and `cdf_lidar.tif` (they are copied again before use, so nothing is written there).
The GeoPackage test (`tests/test_realdata_gpkg.py`) also needs an explorations GeoPackage with three point
layers (`XSECTIONS_GPKG`, default path in `tests/fixtures.py`): it is byte-copied first and only the copy
is opened, and the test checks that the original is unchanged. Its counts and labels are checked only while
the file is the one they were measured on (its SHA-256); otherwise those checks are skipped with a message.
`tests/test_compat_032.py` compares the sheets, previews and models of five 0.3.2 projects pixel for pixel
with the golden files in `tests/data/compat_032/` (made once from 0.3.2; never regenerate them to make a
change pass). The one exception so far: the sheets of the *bytype* case were made again once for 0.3.4, with
the user's approval, when *Data lines: By type* became *Color* from the layer style
(`XSECTIONS_REMAKE_GOLDEN=bytype`, allowed only for the cases listed in the test's `REMADE`).

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
offscreen), which GitHub's runners don't have. Run `scripts\run_tests_parallel.bat` (or `scripts\run_tests.bat`)
before tagging.

---

## License

XSections is free software, licensed under the **GNU General Public License, version 2 (GPL-2.0)**.
See [LICENSE](LICENSE). The plugin zip includes the same file.
