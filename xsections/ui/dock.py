"""The XSections panel: every setting, live readouts, the debounced rebuild, and the export buttons.

Flow: any change -> 300 ms timer -> refresh(): settings() -> core.build.build_section ->
render.scales.plan -> preview.draw / readouts / row problems / header chips / map feedback. A SectionError shows in
the status line at the bottom of the panel, never as a traceback dialog.

Layout (0.3.6, DESIGN.md decision 27, the approved panel mockup; 0.3.7, decision 28): six sections, Line, Surfaces,
Explorations (its subsections Layers and Options: four option buttons, All layers, Depths, Water & screens and
Plotted, each showing a one-line summary of its settings and opening a popup that holds them; one popup open at a
time, closed by a second click, its ✕, Esc or a click anywhere else: widgets.OptionGrid), Other features (Layers),
Scale & sheet (Scale with Distances; Elevations with Room below lowest | Fill sheet under Auto, Lowest | Highest under
Manual; Sheet: Size (a check box per sheet size, and Custom) | Format) and Sheet style (Grid, Depth lines, Page), all
closed whenever the panel opens or a project is loaded; several may be open at once. A closed section is a solid tile,
an open one the navy bar over a framed body on a navy rail; each header carries a summary chip (amber when something
is missing) and an amber count of the layers that need a look. Subsections have navy capital headings; field names
sit above their fields in plain sentence case, two fields to a row; short choices are segmented buttons; set-once
settings fold under a round pill (Units & datum). The layer rows of Surfaces, Explorations and Other features are
cards; an open one joins its section's rail (widgets.LayerCard, the "Flare"). Explanations under the controls (hints)
and the readouts show only with Verbose (the ⋯ menu; per user, widgets.verbose). A real problem of a row (ui.problems:
values left out, a layer gone ...) is one amber line in the row with a count badge and a check card; a guess shows
only its "check" badge; what no row owns is the status line's (a warning amber, an error red; else "Ready · ...").

Point layers (0.3.3, DESIGN.md decision 22): Explorations is a list of point-layer rows (ui.point_rows.ExplorationRow:
own explorations, explorations by others, supply wells...), each with its own layer, fields, types, water fields,
look and "Include in the elevation range"; the rules (within, labels, tops, TD, screens) stay shared. Other features
(0.3.6: seeps and springs as points, creeks as lines, a site as polygons; Other points before) are rows of their own
(OtherPointsRow). The Plotted popup (Explorations › Options) lists everything the rows choose on the section; what he
unticks there is left off this section line (self._hidden, Settings.hidden_points, keyed by the line, the layer id and
the feature id). Rows made from guesses (a fresh project, layers added later) are never saved by themselves.

Surfaces: the ground row (GroundRow), then one row per other surface: a raster (widgets.SurfaceRow) or a MODFLOW 6
model surface (mf6_dialog.ModelSurfaceRow, added with "+ MODFLOW 6…", mf6_dialog.MF6Dialog).

Sheet style (0.3.4, DESIGN.md decision 23): the grid (Green | Gray | Custom: the major and minor lines' colour, width
and line style, 0.3.7: or None, that set of lines left out; the first Custom starts from the preset in use, later ones
keep his values, saved with the project only) and the depth line widths (Black & gray, Color; Reset). An exploration
row drawn in Color follows its layer's QGIS style: the layer's styleChanged re-reads the style box and rebuilds the
section (nothing is saved).

Hover (0.3.1): the preview's hover moves a marker along the section line on the map (preview.hoverChanged /
hoverLeft -> MapFeedback.show_cursor / hide_cursor), and the map cursor near the line moves the preview's guide
(canvas.xyCoordinates -> preview.show_guide, the canvas viewport's Leave -> hide_guide). The preview's Surfaces CSV…
button asks for export_surfaces_csv.
"""
from __future__ import annotations

import contextlib
import csv
import dataclasses
import functools
import math
import os
import re
import traceback
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from qgis.core import (Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsCsException,
                       QgsExpression, QgsExpressionContext, QgsExpressionContextUtils, QgsFeature,
                       QgsFeatureRequest, QgsField, QgsGeometry, QgsMessageLog,
                       QgsPalLayerSettings, QgsPointXY, QgsProject, QgsRasterLayer, QgsUnitTypes,
                       QgsVectorLayer, QgsVectorLayerSimpleLabeling)
from qgis.gui import (QgsAdvancedDigitizingDockWidget, QgsColorButton, QgsDockWidget, QgsMapLayerComboBox,
                      QgsMessageBarItem, QgsRasterBandComboBox, QgsScrollArea)
from qgis.PyQt.QtCore import QEvent, QLocale, QMetaType, QPoint, QSize, Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QColor, QDesktopServices, QDoubleValidator, QFont, QPainter, QPalette
from qgis.PyQt.QtWidgets import (QComboBox, QDialog, QFileDialog, QFrame, QGraphicsOpacityEffect, QGridLayout,
                                 QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QSizePolicy, QStyle,
                                 QStyleOptionToolButton, QStylePainter, QToolButton, QVBoxLayout, QWidget)

from ..core.explorations import not_number_text
from ..core.hover import hover_lines
from ..core.model import (DEPTH_LW_BLACK, DEPTH_LW_COLOR, DEPTH_LW_LIMITS, GRID_PRESETS, GRID_W_MAX, GRID_W_MIN,
                          NO_ATD, NO_POINTS, NO_TYPES, POINT_LAYER_DEFAULTS, SURFACE_COLORS, SURFACE_DEFAULTS,
                          SectionError, Settings, clean_hidden, clean_orientation, clean_other_points, depth_widths,
                          feature_row, grid_spec, hidden_key, hit_settings, layer_rows, line_key, point_legend_name)
from ..core.others import feature_kind
from ..core.surfaces_csv import write_surfaces_csv
from ..render.scales import hit_in_range, runs_below, td_text
from . import problems as P
from . import settings_store
from . import widgets as W
from .map_feedback import MapFeedback
from .maptools import DrawSectionTool, PickLineTool
from .mf6_dialog import MF6Dialog, ModelSurfaceRow, crs_from_text
# the field-name guesses live in ui.point_guess since 0.3.3 (the point rows use them); imported back under the
# 0.3.2 names, which tests import from here
from .point_guess import (ATD_ANY_NAMES, ATD_DATE_NAMES, ATD_DEPTH_NAMES, ATD_ELEV_NAMES, ATD_NAMES,  # noqa: F401
                          BOTTOM_ELEV_NAMES, DEPTH_NAMES, LABEL_NAMES, OTHER_ELEV_NAMES, OTHER_HINTS, POINT_HINTS,
                          SCREEN_BOTTOM_NAMES, SCREEN_TOP_NAMES, TABLE_DATE_NAMES, TABLE_ELEV_NAMES,
                          TABLE_KIND_NAMES, TABLE_NAME_NAMES, TOP_NAMES, TYPE_NAMES, WL_DATE_NAMES, WL_DEPTH_NAMES,
                          WL_ELEV_NAMES, WL_NAMES, _norm, guess_field, guess_in_range, is_other_hint, is_point_hint)
from .point_rows import (ExplorationRow, FitCheckBox, OtherPointsRow, PlottedList, PointRowList, point_layer,
                         table_layer)
from .surfaces_csv_dialog import SurfacesCsvDialog
from .widgets import (CONTROL_H, LINE_STYLE_ICON_SIZE, LINE_STYLE_ICONS, BarSwatch, CardHost,  # noqa: F401
                      ClickableArea, CollapsibleSection, Disclosure, ElidedLabel, Hint, LayerCard, OptionGrid,
                      OptionPopup, Readout, SheetSizeCombo, StatusDot, SurfaceRow, _cbox, _combo, _esc,
                      _field_combo, _narrow, _note, _numeric_field_combo, _px_font, _segmented, _set_combo_data,
                      _spin, add_button, check_row, checkbox_grid, field_box, field_label, hrow, link_button,
                      link_cards, pair, panel_stylesheet, theme_for, wrap_tip)

LOG_TAG = "XSections"
DRAWN = "__drawn__"                      # feature-combo data for a line drawn on the map
LINES_LAYER_NAME = "XSections lines"
LINES_LAYER_PROP = "xsections/lines"

# layer-name hints for a fresh project (no saved settings); the point-layer hints (POINT_HINTS for explorations,
# OTHER_HINTS for other points) come from ui.point_guess
DEM_HINTS = ("lidar", "dem", "dtm", "elev", "terrain")
NOT_DEM_HINTS = ("hillshade", "shade", "ortho", "aerial", "imagery", "image", "photo", "slope", "aspect")
# a line layer is only guessed from its name (no fallback): a contour or a road is not a section line
LINE_HINTS = ("section", "xsec", "x-sec", "profile", "transect")
MAX_GUESSED_ROWS = 6                    # a fresh project gets at most this many exploration rows
LIST_MAX = 6                            # labels named in a readout line before "+N"

SHEET_KEYS = ["letter", "tabloid", "ansic", "archc", "ansid", "archd"]
SHEET_SHORT = {"letter": "Letter", "tabloid": "Tabloid", "ansic": "ANSI C", "archc": "ARCH C", "ansid": "ANSI D",
               "archd": "ARCH D"}
# Scale & sheet › Size (0.3.7, the amendment of D8: no Printers take; a check box per sheet size, the approved
# mockup's round 8): several checked, the smallest that fits among them; one, just that sheet; none, Letter; or Custom
SIZE_DETAIL = {"letter": "8.5 × 11 in", "tabloid": "11 × 17 in", "ansic": "17 × 22 in", "archc": "18 × 24 in",
               "ansid": "22 × 34 in", "archd": "24 × 36 in"}
SIZE_ITEMS = [(k, SHEET_SHORT[k], SIZE_DETAIL[k]) for k in SHEET_KEYS]
SIZE_CUSTOM = ("custom", "Custom", "cut to the drawing")
SIZE_FOOT = "Several: the smallest that fits · One: just that · None: Letter"
SIZE_TIP = "Check several: the smallest that fits. One: just that sheet. None: Letter."     # the field's label
# page orientation (0.3.5, his request): Auto is the search of every earlier version
ORIENT_CHOICES = [("Auto", "auto"), ("Landscape", "landscape"), ("Portrait", "portrait")]
ORIENT_TIPS = ["As fits best: landscape first, then portrait (as before)", "Every sheet landscape",
               "Every sheet portrait"]
ORIENT_CUSTOM_TIP = "Not used with a custom page size: a custom page is sized to the drawing"
EDGE_CHOICES = [("0.5 in", 0.5), ("0.3 in", 0.3)]
EDGE_TIPS = ["Any printer", "Most laser printers (they print to within 0.25 in; check yours)"]
EDGE_VALUES = [v for _, v in EDGE_CHOICES]
FILL_CHOICES = [("Off", "off"), ("Below", "below"), ("Both", "both")]
# Scale & sheet › Elevations under Auto (0.3.7, D6: moved from Sheet style › Grid; their tooltips explain them)
FILL_TIPS = ["Off: leave the paper left over on the sheet blank.",
             "Below (the default): fill the paper left over with whole grid squares under the section, down to the "
             "margin. Room to draw the geology deeper.",
             "Both: fill it with grid squares above and below the section, the larger half below."]
FILL_TIP = "What to do with the paper left over on the sheet"
FILL_CUSTOM_TIP = "Not used with a custom page size: the page is cut to the drawing"
ROOM_TIP = "Grid kept under the lowest point (the lowest bottom or TD label), in paper inches"
Z_AUTO_HINT = ("Auto picks the range from your data plus the room below. Fill sheet turns the paper left over into "
               "whole grid squares.")
# Scale & sheet › Scale (0.3.7, D7: moved from the "Distances & printers" pill)
DISTANCES_TIP = "How distances along the line are written: 1,250 ft, or as stations 12+50"
DISTANCE_TIPS = ["Distances in feet: 1,250", "Distances as stations: 12+50"]
FORMAT_CHOICES = [("PDF (vector)", ("pdf", 300)), ("PNG, 300 dpi", ("png", 300)), ("PNG, 600 dpi", ("png", 600)),
                  ("SVG", ("svg", 300))]
EXPORT_FILTERS = {"pdf": "PDF (*.pdf)", "png": "PNG image (*.png)", "svg": "SVG drawing (*.svg)"}
SCALE_PRESETS = [1, 2, 5, 10, 20, 30, 40, 50, 60, 100, 200, 300, 400, 500, 600, 1000, 2000, 5000]
COMPASS16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
# the six sections' chip keys (chip_texts), in panel order
SECTION_KEYS = ("line", "surfaces", "explorations", "other", "scale", "style")
# the Sheet style keys of its chip ("Defaults" when all are at theirs; the Custom grid's values only matter under
# Custom; 0.3.7: not fill_grid, a Scale & sheet setting now)
STYLE_KEYS = ("grid_color", "depth_lw_black", "depth_lw_color", "shade_below", "show_bends", "compact_layout",
              "edge_margin_in", "show_notes")
GRID_NAMES = {"green": "Green", "gray": "Gray", "custom": "Custom"}
# the Custom grid's line styles (0.3.7, D5: None leaves that set of lines out; a text button, the others icons)
GRID_LINE_STYLES = [("Solid", "solid"), ("Dashed", "dash"), ("Dotted", "dot"), ("None", "none")]
GRID_LINE_TIPS = ["Solid", "Dashed", "Dotted", "No lines"]
GRID_STYLE_WORDS = {"solid": "solid", "dash": "dashed", "dot": "dotted", "none": "none"}     # the legend line
GRID_SPACING_AUTO = "Major lines every inch, minor every tenth."
GRID_SPACING_MANUAL = "Major and minor lines at the spacing below."
# 0.3.6: the texts of the redesigned panel (the explanations that left it are tooltips, and Verbose hints)
GROUND_TIP = "The ground: always drawn; the explorations sit on it. Click to choose its DEM"
LINE_HINT = "Pick a line on the map, draw one, or use the selected feature of the layer."
WITHIN_HINT = "“Within” applies to the Other features point layers too."
DEPTH_LW_HINT = ("Which layers are black, gray or in color is set for each layer, under Explorations › "
                 "<b>Drawn in</b>.")
STYLE_HINT = "The defaults leave the most room to draw and the paper clear for colored pencil."
VERBOSE_TIP = "Hints and notes under the controls"
OTHER_ADD_TIP = "Add a layer of other features: seeps or springs (points), creeks (lines), a site (areas)"
# Explorations › Options (0.3.7, D1): the four buttons (in this order) and what each explains over its summary
OPT_TITLES = ["All layers", "Depths", "Water & screens", "Plotted"]
OPT_TIPS = ["Within, labels and label text, for every layer", "Depth lines, TD labels and where tops come from",
            "Screens, water levels and what is printed beside them",
            "Every exploration on this section: untick one to leave it off"]
OPTIONS_HINT = "Each button opens its options. A second click, ✕, Esc or a click anywhere else closes them."
TOPS_WORDS = {"field_then_dem": "table, else LIDAR", "dem": "LIDAR", "field": "table only"}     # the Depths summary
BESIDE_WORDS = {"off": "nothing beside", "elev": "elevation beside", "elev_date": "elev. + date beside"}
TOP_MAX_DIFF_W = 70     # the LIDAR check's box (0.3.6: 76): its label on one line in the 268 px popup body (a 340 px
                        # dock with the scroll bar); "9999.0 ft" still whole
POPUP_VIEW_MARGIN = 8   # px kept between a popup scrolled into view and the view's edge
GRID_DIM_OPACITY = 0.38  # a None part's colour swatch: the live swatch dimmed (the mockup's .gridtab .dim)

ERROR_COLOR = "#c0392b"
WARN_COLOR = "#9a6700"

# the map cursor near the section line moves the preview's guide
MAP_HOVER_MS = 10           # map mouse moves this close together make one update (each one repaints the preview)
MAP_HOVER_TOLERANCES = 2.5  # near the line: within this many projection tolerances of it,
MAP_HOVER_PX = 15.0         # or this many screen px (the only rule on a ground-only section, which has no tolerance)


# ---------------------------------------------------------------- small helpers (also used by tests)
# (_norm and guess_field live in ui.point_guess since 0.3.3, imported above)
def compass16(azimuth: float) -> str:
    return COMPASS16[int((azimuth % 360.0) / 22.5 + 0.5) % 16]


def fmt_azimuth(azimuth: float) -> str:
    """Whole degrees 000-359 (359.6 reads 000, not 360)."""
    return f"{int(round(azimuth)) % 360:03d}°"


def fmt_ft(value: float, decimals: int = 0) -> str:
    return f"{value:,.{decimals}f} ft"


def fmt_station(st: float) -> str:
    n = int(round(st))
    sign = "-" if n < 0 else ""
    n = abs(n)
    return f"{sign}{n // 100}+{n % 100:02d}"


def fmt_num(v: float) -> str:
    return f"{v:g}" if abs(v - round(v)) > 1e-9 else str(int(round(v)))


def _muted(text: str) -> QLabel:
    """A small muted word beside link buttons ("Start from", "·")."""
    lab = QLabel(text)
    lab.setObjectName("xsMuted")
    f = QFont(lab.font())
    if f.pointSizeF() > 0:
        f.setPointSizeF(f.pointSizeF() * 0.9)
    lab.setFont(f)
    return lab


def fmt_scale(v: float) -> str:
    """A scale in feet per inch for a header chip: 1,000 or 2.5."""
    return f"{int(round(v)):,}" if abs(v - round(v)) < 1e-9 else f"{v:g}"


def pretty_label(text: str) -> str:
    """An end label for display: an apostrophe becomes a prime (A' -> A′)."""
    return (text or "").replace("'", "′")


def sheet_short(name: str) -> str:
    """The sheet's short name from a page name: "Letter 11 × 8.5 in, landscape" -> "Letter"."""
    m = re.match(r"\D*", name or "")
    short = (m.group(0) if m else "").strip(" ,")
    return short or (name or "")


def reverse_hint(azimuth: float, start: str, end: str) -> str:
    """Hint to press Reverse when A' bears 135-315 degrees (sections usually read W->E or S->N)."""
    az = azimuth % 360.0
    if not 135.0 <= az < 315.0:
        return ""
    reading = "south to north" if az < 225.0 else "west to east"
    return f"{end or 'End'} is {compass16(az)} of {start or 'start'}: press Reverse to read {reading}."


def screen_counts(hits) -> Tuple[int, int, int]:
    """(explorations with a screen, measured water levels, ATD water levels) among `hits`."""
    screens = sum(1 for h in hits if getattr(h, "screen_top", None) is not None
                  and getattr(h, "screen_bottom", None) is not None)
    levels = [wl for h in hits for wl in (getattr(h, "water_levels", None) or [])]
    atd = sum(1 for wl in levels if getattr(wl, "kind", "measured") == "atd")
    return screens, len(levels) - atd, atd


def screens_summary(hits) -> str:
    """"3 screens · 3 measured, 2 ATD water levels" (plain text)."""
    n, measured, atd = screen_counts(hits)
    first = f"{n} screen{'s' if n != 1 else ''}"
    total = measured + atd
    if not total:
        return f"{first} · no water levels"
    noun = "water level" if total == 1 else "water levels"
    if measured and atd:
        return f"{first} · {measured} measured, {atd} ATD {noun}"
    return f"{first} · {measured} measured {noun}" if measured else f"{first} · {atd} ATD {noun}"


# ---- the option buttons' summaries (0.3.7, D1: one muted line under each title, following every change)
def all_layers_summary(tolerance_ft: float, vertical: bool, offset: bool) -> str:
    """"150 ft · vertical · name only"."""
    return (f"{fmt_num(round(float(tolerance_ft), 1))} ft · {'vertical' if vertical else 'horizontal'} · "
            f"{'name + offset' if offset else 'name only'}")


def depths_summary(line: bool, td: bool, top_mode: str) -> str:
    """"line · TD · table, else LIDAR"; "no line" without depth lines (TD and tops follow the line)."""
    if not line:
        return "no line"
    return " · ".join(w for w in ("line", "TD" if td else "no TD", TOPS_WORDS.get(top_mode, "")) if w)


def water_summary(on: bool, wl_label: str) -> str:
    """"drawn · elevation beside"; "off" while screens and water levels are not drawn."""
    return f"drawn · {BESIDE_WORDS.get(wl_label, BESIDE_WORDS['off'])}" if on else "off"


def plotted_summary(counts: Optional[Tuple[int, int, int]]) -> str:
    """From PlottedList.counts(): "15 of 16 · 1 off", "16 of 16 · all shown"; "none" when nothing is chosen on the
    section; "–" before a build."""
    if counts is None:
        return "–"
    n, m, k = counts
    if not m:
        return "none"
    return f"{n} of {m} · {k} off" if k else f"{n} of {m} · all shown"


# ---- Scale & sheet › Size (0.3.7, the amendment of D8): its check boxes <-> Settings.sheet + allowed_sheets
def size_text(keys: Sequence[str], custom: bool) -> Tuple[str, str]:
    """(the closed box's text, its tooltip) for the checked sheet `keys` (SHEET_KEYS order) or Custom: "Tabloid",
    "Letter or Tabloid", "Smallest of 3 sizes", "Custom"; "Letter" with none checked (the mockup's round 8)."""
    if custom:
        return "Custom", "Custom: the page is cut to the drawing"
    names = [SHEET_SHORT[k] for k in SHEET_KEYS if k in set(keys)]
    if not names:
        return "Letter", "Nothing checked: Letter"
    if len(names) == 1:
        return names[0], f"{names[0]} only"
    if len(names) == 2:
        text = f"{names[0]} or {names[1]}"
        return text, f"{text}: the smallest that fits"
    return f"Smallest of {len(names)} sizes", f"{', '.join(names)}: the smallest that fits"


def sheet_from_checks(keys: Sequence[str], custom: bool) -> Tuple[str, List[str]]:
    """(Settings.sheet, Settings.allowed_sheets) the Size list writes (no new keys): several checked, "smallest" over
    them (tiling on the largest, as 0.3.6's Smallest that fits over its printers' sheets); one, that sheet and [it];
    none, Letter; Custom, "custom" with the default allowed sheets (a custom page does not use them)."""
    if custom:
        return "custom", list(Settings().allowed_sheets)
    on = [k for k in SHEET_KEYS if k in set(keys)]
    if not on:
        return "letter", ["letter"]
    if len(on) == 1:
        return on[0], [on[0]]
    return "smallest", on


def checks_from_sheet(sheet: str, allowed: Sequence[str]) -> Tuple[List[str], bool]:
    """(the checked sheet keys, Custom) for a stored sheet and allowed list (old projects open as they say): "custom"
    Custom; a sheet key, just that one; "smallest" (or anything else), the known keys of `allowed`, or Letter and
    Tabloid when it names none (as scales.plan reads an empty list)."""
    if sheet == "custom":
        return [], True
    if sheet in SHEET_KEYS:
        return [sheet], False
    on = [k for k in SHEET_KEYS if k in set(allowed or [])]
    return (on or ["letter", "tabloid"]), False


_SCREEN_FLAG = P.SCREEN_FLAG             # (moved to ui.problems in 0.3.6)


def _as_curve(geom: QgsGeometry):
    """A single QgsCurve from a (multi)line geometry, merging parts when they join up; None otherwise."""
    if geom is None or geom.isEmpty():
        return None
    g = geom
    if g.isMultipart():
        merged = g.mergeLines()
        if not merged.isEmpty():
            g = merged
        if g.isMultipart():
            coll = g.constGet()
            if coll.numGeometries() != 1:
                return None
            return coll.geometryN(0).clone()
    part = g.constGet()
    return part.clone() if hasattr(part, "reversed") else None


def _crs_factor_to_ft(crs: QgsCoordinateReferenceSystem) -> float:
    if not crs.isValid() or crs.isGeographic():
        return math.nan
    return QgsUnitTypes.fromUnitToUnitFactor(crs.mapUnits(), Qgis.DistanceUnit.Feet)


def _safe_filename(text: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", text).strip() or "section"


class LineLocator:
    """Where a point projects onto a section line, by the rule core uses for the explorations
    (closestSegmentWithContext, the offset measured to the foot), all in the line's CRS units."""

    def __init__(self, line: QgsGeometry):
        self.line = line
        self.verts = [(v.x(), v.y()) for v in line.vertices()]
        self.cum = [0.0]
        for (ax, ay), (bx, by) in zip(self.verts, self.verts[1:]):
            self.cum.append(self.cum[-1] + math.hypot(bx - ax, by - ay))

    def locate(self, point: QgsPointXY) -> Optional[Tuple[float, float, str, QgsPointXY]]:
        """(distance along the line, offset, "L" or "R", foot on the line) of `point`; None past either end of
        the line (the foot would be the end itself) or when the point does not project."""
        nseg = len(self.verts) - 1
        if nseg < 1:
            return None
        sqr, foot, after, left = self.line.closestSegmentWithContext(QgsPointXY(point))
        if sqr < 0 or not math.isfinite(sqr):
            return None
        seg = min(max(after - 1, 0), nseg - 1)
        (ax, ay), (bx, by) = self.verts[seg], self.verts[seg + 1]
        seg_len = self.cum[seg + 1] - self.cum[seg]
        along = ((point.x() - ax) * (bx - ax) + (point.y() - ay) * (by - ay)) / seg_len if seg_len > 0 else 0.0
        eps = 1e-9 * max(1.0, seg_len)
        if (seg == 0 and along < -eps) or (seg == nseg - 1 and along > seg_len + eps):
            return None
        dist = min(self.cum[seg] + math.hypot(foot.x() - ax, foot.y() - ay), self.cum[-1])
        return dist, math.sqrt(sqr), "R" if left > 0 else "L", QgsPointXY(foot)


class ScaleCombo(QComboBox):
    """Editable "1 in = ___ ft" combo with engineer's-scale presets."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for v in SCALE_PRESETS:
            self.addItem(str(v), float(v))
        validator = QDoubleValidator(0.001, 1.0e7, 3, self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        validator.setLocale(QLocale.c())
        self.lineEdit().setValidator(validator)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(4)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def value(self) -> Optional[float]:
        try:
            v = float(self.currentText().replace(",", "").strip())
        except ValueError:
            return None
        return v if v > 0 else None

    def setValue(self, v: float) -> None:
        self.setEditText(fmt_num(float(v)))


# (_combo, _segmented, _narrow, _set_combo_data, _spin, _field_combo, _numeric_field_combo, _note, _esc and _cbox
# live in ui.widgets since 0.3.3, imported above: the point rows use them too)
def _edge_choice(value: Any) -> float:
    """The printer edge offered nearest to a stored value (0.5 in for anything unreadable)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return EDGE_VALUES[0]
    return min(EDGE_VALUES, key=lambda e: abs(e - v)) if math.isfinite(v) else EDGE_VALUES[0]


def _readout() -> Readout:
    """The muted lines at the bottom of a section (0.3.6: a Verbose note, widgets.Readout; wanted only while it has
    something to say)."""
    lab = Readout("")
    lab.setWanted(False)
    return lab


def _html(lines: Iterable[str]) -> str:
    return "<br>".join(line for line in lines if line)


def _tool(icon: str, text: str, tip: str, checkable: bool = False) -> QToolButton:
    b = QToolButton()
    b.setObjectName("xsTool")
    if icon:
        b.setIcon(QgsApplication.getThemeIcon(icon))
        b.setIconSize(QSize(14, 14))
    b.setText(text)
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if text and icon
                         else (Qt.ToolButtonStyle.ToolButtonIconOnly if icon else Qt.ToolButtonStyle.ToolButtonTextOnly))
    b.setFixedHeight(CONTROL_H + 2)
    b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)      # hrow() makes row buttons share the width
    return b


class GroundRow(LayerCard):
    """The first card of Surfaces (0.3.6): the ground, always drawn (no check box, nothing to move or remove: no ⋯),
    its black bar, "Ground" over the DEM's name, band and cell size; its editor holds the DEM layer and band (the dock
    builds them into `editor`). A click on the card opens or closes it."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsGroundCard")
        self.swatch = BarSwatch("#111111", self.header)
        self.swatch.setToolTip("The ground line")
        self.name_area = ClickableArea(self.header)
        self.name_area.setToolTip(GROUND_TIP)
        na = QVBoxLayout(self.name_area)
        na.setContentsMargins(0, 0, 0, 0)
        na.setSpacing(0)
        self.name_label = ElidedLabel("Ground", parent=self.name_area)
        self.sub_label = ElidedLabel("", small=True, parent=self.name_area)
        na.addWidget(self.name_label)
        na.addWidget(self.sub_label)
        self.name_area.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._place_header(None, self.swatch, self.name_area, None)
        self.editor.setObjectName("xsSurfaceEditor")
        self.editor_layout = QVBoxLayout(self.editor)
        self.editor_layout.setContentsMargins(9, 8, 8, 11)
        self.editor_layout.setSpacing(8)
        self.name_area.clicked.connect(self.toggle_editor)

    def set_editor_open(self, on: bool) -> None:
        """Open or close the DEM's editor; while open the name and its subtitle are semibold (as the point rows)."""
        super().set_editor_open(on)
        self.sub_label.setBold(bool(on))


class _StatusBar(QWidget):
    """The status line under the scroll area (0.3.6): a 1 px rule on top (field_line), its dot and texts."""

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(0, 0, self.width(), 1, theme_for(self.palette()).field_line)
        p.end()


class _FitRow(QWidget):
    """Widgets on one line (0.3.6, the mockup's rows), `last` at its right end; where the panel is too narrow for one
    line at their natural widths (260 px with the Windows font), `last` goes under the others: every word stays
    whole, nothing is clipped. `fill`: the widgets share the width (stretch 1 each; `last` then fills its own line);
    else they keep their widths and a stretch puts `last` at the right (`gap` px clear of the others at least)."""

    def __init__(self, widgets: Sequence[QWidget], last: QWidget, spacing: int = 6, fill: bool = False,
                 gap: int = 0, line_spacing: int = 2, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._widgets, self._last = list(widgets), last
        self._spacing, self._fill, self._gap = spacing, fill, gap
        self._wrapped = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(line_spacing)
        self._top = QHBoxLayout()
        self._top.setContentsMargins(0, 0, 0, 0)
        self._top.setSpacing(spacing)
        for w in self._widgets:
            self._add(self._top, w)
        if not fill:
            self._top.addStretch(1)
        self._add(self._top, last)
        self._bottom = QHBoxLayout()
        self._bottom.setContentsMargins(0, 0, 0, 0)
        if not fill:
            self._bottom.addStretch(1)
        lay.addLayout(self._top)
        lay.addLayout(self._bottom)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def _add(self, lay: QHBoxLayout, w: QWidget) -> None:
        if self._fill:
            lay.addWidget(w, 1)
        else:
            lay.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)

    @staticmethod
    def _need(w: QWidget) -> int:
        return w.minimumWidth() if w.minimumWidth() > 0 else max(w.sizeHint().width(), w.minimumSizeHint().width())

    def one_line_width(self) -> int:
        """The width all of them need on one line."""
        ws = [self._need(w) for w in self._widgets + [self._last]]
        return sum(ws) + self._spacing * (len(ws) - 1) + self._gap

    def wrapped(self) -> bool:
        """`last` is on a line of its own."""
        return self._wrapped

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        wrap = self.width() < self.one_line_width()
        if wrap == self._wrapped:
            return
        self._wrapped = wrap
        src, dst = (self._top, self._bottom) if wrap else (self._bottom, self._top)
        src.removeWidget(self._last)
        self._add(dst, self._last)


class _GridColorButton(QgsColorButton):
    """A Custom grid colour (0.3.7 fix, D5). Disabled (its lines None), it draws as the live swatch at
    GRID_DIM_OPACITY, the mockup's dimmed cell, instead of Qt's disabled icon: a flat light gray, on a dark panel
    brighter than the live swatch beside it, read as a pale colour in use rather than grayed out."""

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        if e.type() == QEvent.Type.EnabledChange:
            if self.isEnabled():
                if self.graphicsEffect() is not None:
                    self.setGraphicsEffect(None)
            elif self.graphicsEffect() is None:
                dim = QGraphicsOpacityEffect(self)
                dim.setOpacity(GRID_DIM_OPACITY)
                self.setGraphicsEffect(dim)

    def paintEvent(self, e) -> None:
        if self.isEnabled():
            super().paintEvent(e)
            return
        p = QStylePainter(self)            # (QToolButton's own paint, as if enabled: the swatch in its colour)
        opt = QStyleOptionToolButton()
        self.initStyleOption(opt)
        opt.state |= QStyle.StateFlag.State_Enabled
        pal = QPalette(opt.palette)
        pal.setCurrentColorGroup(QPalette.ColorGroup.Active)
        opt.palette = pal
        p.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, opt)
        p.end()


class _GridTable(QWidget):
    """Sheet style › Grid › Custom (0.3.7, the mockup's table): Major / Minor x Color, Width, Line (Solid | Dashed |
    Dotted | None). The label, colour and width columns at least COLS px wide, the Line column takes the rest (at a
    340 px dock 134 px: its four buttons whole); where it is narrower than a Line control needs (the 260 px dock), each
    part's Line control goes on a row of its own under its label, colour and width, the full width, and the "Line"
    heading hides. `rows`: (label, colour, width, line style) of the major then the minor lines."""

    COLS = (36, 32, 70)                    # minimum widths of the label, colour and width columns (0.3.6: 40, 38, 70)
    H_SPACING, V_SPACING = 6, 5

    def __init__(self, rows: Sequence[Tuple[QWidget, QWidget, QWidget, W.SegmentedControl]],
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._rows = [tuple(r) for r in rows]
        self._wrapped: Optional[bool] = None
        self._heads = [field_label(text) for text in ("Color", "Width")]
        self.line_head = field_label("Line")
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(self.H_SPACING)
        self._grid.setVerticalSpacing(self.V_SPACING)
        for col, width in enumerate(self.COLS):
            self._grid.setColumnMinimumWidth(col, width)
        self._grid.setColumnStretch(3, 1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._place(False)

    def wrapped(self) -> bool:
        """Each Line control is on a row of its own (the panel is too narrow for it beside the width)."""
        return bool(self._wrapped)

    def line_room(self) -> int:
        """The Line column's width beside the others at this width."""
        return self.width() - sum(self.COLS) - 3 * self.H_SPACING

    def _place(self, wrapped: bool) -> None:
        if wrapped == self._wrapped:
            return
        self._wrapped = wrapped
        g = self._grid
        for w in self._heads + [self.line_head] + [x for r in self._rows for x in r]:
            g.removeWidget(w)
        g.addWidget(self._heads[0], 0, 1)
        g.addWidget(self._heads[1], 0, 2)
        if not wrapped:
            g.addWidget(self.line_head, 0, 3)
        self.line_head.setHidden(wrapped)
        for i, (lab, color, width, style) in enumerate(self._rows):
            r = 1 + (2 * i if wrapped else i)
            g.addWidget(lab, r, 0)
            g.addWidget(color, r, 1)
            g.addWidget(width, r, 2)
            if wrapped:
                g.addWidget(style, r + 1, 0, 1, 4)
            else:
                g.addWidget(style, r, 3)

    def _reflow(self) -> None:
        if not self.isVisible():           # (a hidden table has no width yet; its show checks again)
            return
        need = max([r[3].neededWidth() for r in self._rows] or [0])      # (each button its text or icon, whole)
        self._place(self.line_room() < need)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._reflow()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._reflow()


# ---------------------------------------------------------------- the dock
class XSectionsDock(QgsDockWidget):
    """The XSections panel. `preview` is the PreviewWidget in the bottom dock (may be None in tests)."""

    def __init__(self, iface, preview=None, parent: Optional[QWidget] = None):
        super().__init__("XSections", parent)
        self.setObjectName("XSectionsDock")
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.preview = preview
        self.feedback = MapFeedback(self.canvas)

        self.model = None                 # last successful SectionModel
        self.plan = None                  # and its Plan
        self.last_error = ""
        self._settings = Settings()
        self._drawn_wkt = ""
        self._drawn_crs = ""
        self._drawn_desc = "Drawn on map"
        self._reversed_from: Optional[Tuple[str, int]] = None   # (layer id, fid) when the drawn line is a reversed feature
        self._applying = 0
        self._user_changed = False
        self._stale = True
        # Sheet style > Grid: Custom chosen once in this project (its first time starts from the preset in use), and
        # the preset in use before Custom ("green" or "gray"; currentIndexChanged comes after the old one is gone)
        self._grid_custom_used = False
        self._grid_last_preset = "green"
        self._layer_conns: List[Tuple[str, str, Any]] = []   # (layer id, signal name, slot)
        self._draw_tool: Optional[DrawSectionTool] = None
        self._pick_tool: Optional[PickLineTool] = None
        self._prev_tool = None
        self._own_cad: Optional[QgsAdvancedDigitizingDockWidget] = None
        # rows are added by themselves (a fresh project, layers added later) only while these are False: the user
        # removed the last exploration (or Other points) row, or a project was read (until it is read or cleared)
        self._points_none = False
        self._others_none = False
        self._hidden: List[str] = []      # explorations he left off, every line: "LINEKEY|LAYERID|FID"
        # line layers removed while left-off entries were kept for their lines: old id -> (name, fid of the line in
        # use, or None); the same layer added again (a new id) takes those entries (_on_layers_added)
        self._gone_lines: Dict[str, Tuple[str, Optional[int]]] = {}
        self._mapped: set = set()         # 0.3.6: the model warnings shown as the rows' problems (_update_problems)
        self._message_kind = ""           # "error" | "warn": what the status line's message is (its dot)
        self._removing_layers = False     # the project is removing layers: the layer boxes' moves are not choices
        self._was_closed = True           # the panel was closed (not just behind another tab): collapse on show
        self._theme_key: Tuple = ()
        self._in_theme = False
        self.sections: List[CollapsibleSection] = []
        self._disclosures: List[Disclosure] = []
        self.surface_rows: List[SurfaceRow] = []

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._on_timer)
        # layers added: the rows show their layers again once every layer box has the new layers (their models hear
        # of them after the dock does: _on_layers_added)
        self._resync_timer = QTimer(self)
        self._resync_timer.setSingleShot(True)
        self._resync_timer.setInterval(0)
        self._resync_timer.timeout.connect(self._resync_point_rows)

        # hover: who put the marker on the map ("preview", "map" or ""), the map cursor waiting for _map_timer
        # (canvas CRS), and the section line as the map hover reads it (built once per model and canvas CRS)
        self._cursor_from = ""
        self._map_point: Optional[QgsPointXY] = None
        self._map_line: Optional[Tuple[LineLocator, Optional[QgsCoordinateTransform]]] = None
        self._map_viewport = None
        self._preview_conns: List[Tuple[Any, Any]] = []
        self._map_timer = QTimer(self)
        self._map_timer.setSingleShot(True)
        self._map_timer.setInterval(MAP_HOVER_MS)
        self._map_timer.timeout.connect(self._on_map_hover)

        self._build_ui()
        self.closedStateChanged.connect(self._on_closed_state_changed)
        with self._quiet():
            self.apply_settings(Settings())
        self._connect_widgets()
        self._connect_hover()
        W.verbose_hub().changed.connect(self._on_verbose_changed)      # (another dock, a test: undone in cleanup)
        self.collapse_all()

    # ================================================================ UI construction
    def _build_ui(self) -> None:
        outer = QWidget()
        outer.setObjectName("xsPanel")
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(4, 2, 4, 6)
        outer_lay.setSpacing(5)

        self.scroll = QgsScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.content = content
        lay = QVBoxLayout(content)
        lay.setContentsMargins(2, 4, 2, 2)
        lay.setSpacing(0)                 # (the sections' own bottom margins space them: 3 px closed, 10 px open)
        self.scroll.setWidget(content)

        for build in (self._build_line_group, self._build_ground_group, self._build_explorations_group,
                      self._build_other_group, self._build_export_group, self._build_style_group):
            lay.addWidget(build())
        self.sections[0].header.first = True
        self.sections[-1].header.last = True
        lay.addStretch(1)
        outer_lay.addWidget(self.scroll, 1)

        # the status line (0.3.6): a dot, then the message (a warning amber, an error red) or "Ready · ..."
        self.status_bar = _StatusBar()
        sl = QHBoxLayout(self.status_bar)
        sl.setContentsMargins(10, 6, 10, 6)
        sl.setSpacing(7)
        self.status_dot = StatusDot()
        dot_box = QWidget()                      # the dot beside the first line of a wrapped message
        dl = QVBoxLayout(dot_box)
        dl.setContentsMargins(0, 5, 0, 0)
        dl.setSpacing(0)
        dl.addWidget(self.status_dot)
        dl.addStretch(1)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.message.setFont(_px_font(self.message.font(), 11.5))
        self.message.hide()
        self.status_text = QLabel("")
        self.status_text.setObjectName("xsStatus")
        self.status_text.setWordWrap(True)
        self.status_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status_text.setFont(_px_font(self.status_text.font(), 11.5))
        self.status_text.hide()
        sl.addWidget(dot_box, 0)
        sl.addWidget(self.message, 1)
        sl.addWidget(self.status_text, 1)
        self.status_bar.hide()
        outer_lay.addWidget(self.status_bar)

        # action bar: Refresh, ⋯ (points CSV, save line, Verbose), Export…
        self.btn_refresh = _tool("/mActionRefresh.svg", "", "Refresh: rebuild the section now (after editing "
                                                            "layers, for example)")
        self.btn_refresh.setFixedSize(32, 28)
        self.btn_more = _tool("", "⋯", "More actions")
        self.btn_more.setFixedSize(32, 28)
        self.btn_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more = QMenu(self.btn_more)
        more.setToolTipsVisible(True)
        self.btn_csv = more.addAction(QgsApplication.getThemeIcon("/mActionFileSaveAs.svg"), "Export points CSV…")
        self.btn_csv.setToolTip("One row per plotted exploration: station, offset, side, top, bottom, flags")
        self.act_save_line = more.addAction(QgsApplication.getThemeIcon("/mActionAddLayer.svg"), "Save line to layer")
        self.act_save_line.setToolTip(f'Add this section line to the temporary layer "{LINES_LAYER_NAME}"')
        more.addSeparator()
        # Verbose (0.3.6, D13): the hints and notes under the controls, per user (QgsSettings), off by default
        self.act_verbose = more.addAction("Verbose")
        self.act_verbose.setCheckable(True)
        self.act_verbose.setChecked(W.verbose())
        self.act_verbose.setToolTip(VERBOSE_TIP)
        self.btn_more.setMenu(more)
        self.btn_export = QPushButton("Export…")
        self.btn_export.setObjectName("xsPrimary")
        self.btn_export.setToolTip("Export the section at scale to PDF, PNG or SVG")
        self.btn_export.setDefault(True)
        self.btn_export.setFixedHeight(28)
        self.btn_export.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        bl.addWidget(self.btn_refresh)
        bl.addWidget(self.btn_more)
        bl.addWidget(self.btn_export, 1)
        outer_lay.addWidget(bar)
        # the one check card of the panel (0.3.6, D15): a child of the panel, opened by a click on a row's badge
        self.card_host = CardHost(outer)
        outer._xs_card_host = self.card_host
        self.setWidget(outer)
        self.setMinimumWidth(260)
        self._apply_theme()

    def _section(self, title: str, icon: str, name: str) -> CollapsibleSection:
        sec = CollapsibleSection(title, icon, name)
        self.sections.append(sec)
        return sec

    def _more(self, sec, text: str) -> Disclosure:
        """A pill (0.3.6: a round button opening a dashed box) at the end of `sec` (a section or a subsection)."""
        d = Disclosure(text)
        self._disclosures.append(d)
        sec.addWidget(d)
        return d

    def _build_line_group(self) -> QWidget:
        g = self._section("Line", "line", "xsectionsLineGroup")
        self.line_layer = QgsMapLayerComboBox()
        self.line_layer.setFilters(Qgis.LayerFilter.LineLayer)
        self.line_layer.setAllowEmptyLayer(True, "(none: draw on map)")
        _narrow(self.line_layer)
        self.line_feature = QComboBox()
        _narrow(self.line_feature)
        g.addWidget(pair(field_box("Layer", self.line_layer), field_box("Feature", self.line_feature)))

        # (0.3.6: text only, as the mockup)
        self.btn_pick = _tool("", "Pick", "Click a line feature on the map (any visible line layer)", checkable=True)
        self.btn_draw = _tool("", "Draw", "Draw on the map: click vertices, right-click to finish, Esc to cancel. "
                                          "Snapping works.", checkable=True)
        self.btn_selected = _tool("", "Selected", "Use the selected feature of the line layer (or of the active "
                                                  "layer)")
        g.addWidget(hrow(self.btn_pick, self.btn_draw, self.btn_selected))
        self.line_hint = Hint(LINE_HINT)
        g.addWidget(self.line_hint)

        # Ends: A to A′, Reverse, and "Save to layer" at the right
        self.start_label = QLineEdit()
        self.end_label = QLineEdit()
        for e, tip in ((self.start_label, "Label of the start (left end) of the section"),
                       (self.end_label, "Label of the end (right end) of the section")):
            e.setFixedWidth(54)
            e.setToolTip(tip)
        self.btn_reverse = _tool("/mActionReverseLine.svg", "", "Reverse: swap the ends, so A is at the other end "
                                                                "(your layer is not edited)")
        if self.btn_reverse.icon().isNull():
            self.btn_reverse.setText("⇄")
        self.btn_reverse.setFixedSize(30, CONTROL_H)
        self.btn_save_line = link_button("Save to layer", f'Add this section line to the temporary layer '
                                                          f'"{LINES_LAYER_NAME}"')
        self.btn_save_line.setFont(_px_font(self.btn_save_line.font(), 11.0))
        ends = field_label("Ends")
        ends.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        to = QLabel("to")
        to.setObjectName("xsMuted")
        self.ends_row = _FitRow([ends, self.start_label, to, self.end_label, self.btn_reverse], self.btn_save_line,
                                gap=12)
        g.addWidget(self.ends_row)
        self.line_readout = _readout()
        g.addWidget(self.line_readout)
        self.grp_line = g
        return g

    def _build_ground_group(self) -> QWidget:
        g = self._section("Surfaces", "surfaces", "xsectionsGroundGroup")
        # the cards: the ground first, then the other surfaces (frameless: each row is a card, 0.3.6)
        self.surface_list = QWidget()
        self.surface_list.setObjectName("xsSurfaceRows")
        self._surface_layout = QVBoxLayout(self.surface_list)
        self._surface_layout.setContentsMargins(0, 0, 0, 0)
        self._surface_layout.setSpacing(4)

        # the ground: always drawn, cannot be removed; its editor holds the DEM layer and band
        self.ground_row = GroundRow()
        self.ground_name = self.ground_row.name_area
        self.ground_title = self.ground_row.name_label
        self.ground_sub = self.ground_row.sub_label
        self.ground_editor = self.ground_row.editor
        self.dem_layer = QgsMapLayerComboBox()
        self.dem_layer.setFilters(Qgis.LayerFilter.RasterLayer)
        self.dem_layer.setAllowEmptyLayer(True, "(choose the ground DEM)")
        _narrow(self.dem_layer)
        self.dem_band = QgsRasterBandComboBox()
        _narrow(self.dem_band, 4)
        self.ground_row.editor_layout.addWidget(pair(field_box("DEM layer", self.dem_layer),
                                                     field_box("Band", self.dem_band), (3, 2)))
        self._surface_layout.addWidget(self.ground_row)
        g.addWidget(self.surface_list)
        g.body.watch(self.ground_row)
        self.ground_row.editorToggled.connect(self._link_surface_cards)
        self.ground_row.checksChanged.connect(self._update_counts)
        self._link_surface_cards()

        # + Surface, + Bands…, + MODFLOW 6… in one row (0.3.6); each as wide as its text at least
        self.btn_add_surface = _tool("", "+ Surface", "Add another raster line: a water table, a model layer…")
        self.btn_add_bands = _tool("", "+ Bands…", "One surface per band of a multi-band raster")
        self.btn_add_bands.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._bands_menu = QMenu(self.btn_add_bands)
        self.btn_add_bands.setMenu(self._bands_menu)
        self.btn_add_mf6 = _tool("", "+ MODFLOW 6…", "Surfaces read from a MODFLOW 6 model run: the model top, "
                                                    "layer bottoms, heads and the water table")
        for b in (self.btn_add_surface, self.btn_add_bands, self.btn_add_mf6):
            b.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)   # equal, but never cut short
        self.add_surfaces_row = _FitRow([self.btn_add_surface, self.btn_add_bands], self.btn_add_mf6, spacing=5,
                                        fill=True, line_spacing=5)
        g.addWidget(self.add_surfaces_row)

        self.units_more = self._more(g, "Units & datum")
        self.z_units = _combo([("Auto (from the layer)", "auto"), ("Feet", "ft"), ("US survey feet", "ftUS"),
                               ("Meters (converted to feet)", "m")])
        self.z_units.setToolTip("Elevation units of the ground DEM")
        self.datum = QLineEdit()
        self.datum.setPlaceholderText("e.g. NAVD88")
        self.datum.setToolTip("Vertical datum, printed in the axis titles and notes")
        self.units_more.addWidget(pair(field_box("Ground units", self.z_units),
                                       field_box("Vertical datum", self.datum)))
        self.ground_readout = _readout()
        g.addWidget(self.ground_readout)
        self.grp_ground = g
        return g

    def _build_explorations_group(self) -> QWidget:
        g = self._section("Explorations", "explorations", "xsectionsExplorationsGroup")
        # Layers: one row per point layer (ui.point_rows.ExplorationRow), drawn top first
        self.layers_note = Hint("top drawn first", rich=False)
        self.layers_note.setHead(True)
        self.layers_note.setToolTip("Layers are drawn top first")
        layers = g.add_subsection("Layers", [self.layers_note])
        self.explo_list = PointRowList(self._new_explo_row)
        layers.addWidget(self.explo_list)
        self.btn_add_points = add_button("+ Add layer", "Add an explorations layer: your own, explorations by "
                                                        "others, supply wells…")
        layers.addWidget(self.btn_add_points)
        self.explo_list.set_band_host(g.body)

        # Options (0.3.7, D1, D2): four buttons, each with a summary of its settings, whose popups (children of the
        # panel's content, over the sections below) hold the rules every row follows
        self.options_sub = g.add_subsection("Options")
        self.opt_grid = OptionGrid(self.content)
        self.options_sub.addWidget(self.opt_grid)
        self.options_hint = Hint(OPTIONS_HINT)
        self.options_sub.addWidget(self.options_hint)
        self._build_all_layers_group(self.opt_grid)
        self._build_depth_group(self.opt_grid)
        self._build_screens_group(self.opt_grid)
        self._build_plotted_group(self.opt_grid)
        self.opt_all, self.opt_depths, self.opt_water, self.opt_plotted = self.opt_grid.buttons()
        self.opt_grid.popupToggled.connect(self._on_popup_toggled)
        self.explo_readout = _readout()
        g.addWidget(self.explo_readout)
        self.grp_explo = g
        return g

    def _build_all_layers_group(self, grid: OptionGrid) -> OptionPopup:
        """Explorations › Options › All layers (0.3.7: a popup; a subsection in 0.3.6): Within, Labels and Label
        text."""
        _b, pop = grid.add_option(OPT_TITLES[0], OPT_TIPS[0])
        self.tolerance = _spin(0.0, 1.0e6, 1, 10.0, " ft of the line")
        self.tolerance.setToolTip("Explorations and other points within this distance of the line are projected "
                                  "onto it")
        self.label_dir = _segmented([("Vertical", True), ("Horizontal", False)],
                                    ["Labels written upward", "Horizontal labels, staggered"])
        pop.addWidget(pair(field_box("Within", self.tolerance), field_box("Labels", self.label_dir)))
        self.label_text = _combo([("Name only", False), ("Name + offset and direction", True)])
        self.label_text.setToolTip("Name + offset: \"MW-3 · 40 ft S\" = projected 40 ft south onto the line")
        pop.addWidget(field_box("Label text", self.label_text))
        self.within_hint = Hint(WITHIN_HINT)
        pop.addWidget(self.within_hint)
        self.pop_all = pop
        return pop

    def _build_depth_group(self, grid: OptionGrid) -> OptionPopup:
        """Explorations › Options › Depths (0.3.7: a popup, without the Checks pill, D4; a subsection in 0.3.6, a
        section of its own before): Depth line, TD label, Tops from, 0 means missing and the LIDAR check."""
        _b, pop = grid.add_option(OPT_TITLES[1], OPT_TIPS[1])
        self.depth_line = _cbox("Depth line", "Draw a line from the top of each exploration down to its bottom")
        self.td_label = _cbox("TD label", "Label the total depth, as TD 50′, just below the bottom of each line")
        pop.addWidget(check_row(self.depth_line, self.td_label))
        self.top_mode = _combo([("Table, else LIDAR at the exploration", "field_then_dem"),
                                ("LIDAR at the exploration", "dem"), ("Table only", "field")], elide=True)
        self.top_mode.setLeadTip("Where each exploration's top comes from (all layers)")   # (+ the text, when cut)
        pop.addWidget(field_box("Tops from", self.top_mode))
        self.zero_missing = _cbox("0 means missing",
                                  "Tops, depths, screens and water levels of 0 are taken as missing (shapefiles store "
                                  "an empty number as 0). Untick it if an elevation of 0 ft (sea level) is real; "
                                  "other features' elevation fields follow it too.")
        pop.addWidget(self.zero_missing)
        self.top_max_diff = _spin(0.0, 1.0e5, 1, 5.0, " ft")
        self.top_max_diff.setToolTip("A table top further than this from LIDAR is replaced by LIDAR (flagged). When "
                                     "that happens, a table bottom further than this from LIDAR top − depth is "
                                     "replaced too. 0 turns the checks off.")
        self.top_max_diff.setFixedWidth(TOP_MAX_DIFF_W)
        self.top_max_diff.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        before = QLabel("Ignore a table top off LIDAR by over")
        before.setWordWrap(True)
        before.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        before.setToolTip(self.top_max_diff.toolTip())
        self.top_max_diff_row = QWidget()
        rl = QHBoxLayout(self.top_max_diff_row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(5)
        rl.addWidget(before, 1)
        rl.addWidget(self.top_max_diff, 0)
        self.top_max_diff_row.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        pop.addWidget(self.top_max_diff_row)
        self.depth_readout = _readout()
        pop.addWidget(self.depth_readout)
        self.pop_depths = self.grp_depth = pop
        return pop

    def _build_screens_group(self, grid: OptionGrid) -> OptionPopup:
        """Explorations › Options › Water & screens (0.3.7: a popup; a subsection in 0.3.6, the Screens & water
        section before): Draw them, Print beside."""
        _b, pop = grid.add_option(OPT_TITLES[2], OPT_TIPS[2])
        self.screens = _cbox("Draw them", "Draw screens and water levels: well screens, and measured and ATD water "
                             "levels, from each layer's fields or its table of water levels")
        self.screens.setMinimumHeight(CONTROL_H)
        self.wl_label = _segmented([("Off", "off"), ("Elev.", "elev"), ("+ date", "elev_date")],
                                   ["No text", "The elevation beside each water level", "Elevation and date"])
        pop.addWidget(pair(self.screens, field_box("Print beside", self.wl_label)))   # (halves: 0.3.6's 5 : 4 stacks
                                                                                      # in the 268 px popup body)
        self.screens_readout = _readout()
        pop.addWidget(self.screens_readout)
        self.pop_water = self.grp_screens = pop
        return pop

    def _build_plotted_group(self, grid: OptionGrid) -> OptionPopup:
        """Explorations › Options › Plotted (0.3.7, D3: a popup; a subsection in 0.3.6): every exploration the rows
        choose on this section, a checklist; unticked ones are left off this line. Its count and Show all sit in the
        popup's header."""
        self.plotted = PlottedList()
        _b, pop = grid.add_option(OPT_TITLES[3], OPT_TIPS[3], after_title=[self.plotted.count_label],
                                  links=[self.plotted.btn_show_all])
        pop.body_layout.setContentsMargins(8, 7, 8, 9)
        pop.addWidget(self.plotted)
        self.pop_plotted = pop
        return pop

    def _build_other_group(self) -> QWidget:
        g = self._section("Other features", "other", "xsectionsOtherGroup")
        # layers of other features: points (seeps, springs), lines (creeks), polygons (a site); a symbol or a
        # bracket and a label each (ui.point_rows.OtherPointsRow)
        layers = g.add_subsection("Layers")
        self.other_list = PointRowList(self._new_other_row)
        layers.addWidget(self.other_list)
        self.btn_add_other = add_button("+ Add layer", OTHER_ADD_TIP)
        layers.addWidget(self.btn_add_other)
        self.other_readout = _readout()
        layers.addWidget(self.other_readout)
        self.other_list.set_band_host(g.body)
        self.grp_other = g
        return g

    def _build_export_group(self) -> QWidget:
        g = self._section("Scale & sheet", "scale", "xsectionsExportGroup")
        defaults = Settings()
        # Scale: the two scales, then how distances are written (0.3.7, D7: the "Distances & printers" pill before)
        sub = g.add_subsection("Scale")
        self.h_scale = ScaleCombo()
        self.v_scale = ScaleCombo()
        self.h_scale.setToolTip("Horizontal scale: feet per inch of paper")
        self.v_scale.setToolTip("Vertical scale: feet per inch of paper")
        sub.addWidget(pair(field_box("Horizontal", hrow("1 in =", self.h_scale, "ft", spacing=4)),
                           field_box("Vertical", hrow("1 in =", self.v_scale, "ft", spacing=4))))
        self.distance_labels = _segmented([("Feet", "feet"), ("Stations", "station")], DISTANCE_TIPS)
        sub.addWidget(field_box("Distances", self.distance_labels, tip=wrap_tip(DISTANCES_TIP)))

        # Elevations: Auto | Manual; under Auto the room below the lowest point and the fill of the paper left over
        # (0.3.7, D6: from Sheet style › Grid), under Manual the range typed
        sub = g.add_subsection("Elevations")
        self.z_mode = _segmented([("Auto", "auto"), ("Manual", "manual")],
                                 ["Rounded to the major grid", "Type the lowest and highest elevations"])
        # (beside Auto | Manual: "Split sheets" only while the narrowest panel has no room for the whole text)
        self.tile = FitCheckBox("Split across sheets", "Split sheets")
        self.tile.setToolTip("Tile along the section with match lines and one major interval of overlap")
        self.tile.setMinimumHeight(CONTROL_H)
        sub.addWidget(pair(self.z_mode, self.tile, (5, 4)))
        self.below_in = _spin(0.0, 20.0, 2, 0.25, " in")
        self.below_in.setToolTip(wrap_tip(ROOM_TIP))           # (0.3.7 finish, wrap_tip: a long tooltip wraps)
        self.fill_grid = _segmented(FILL_CHOICES, [wrap_tip(tip) for tip in FILL_TIPS])
        _set_combo_data(self.fill_grid, defaults.fill_grid)
        self.fill_grid.setToolTip(wrap_tip(FILL_TIP))
        self.z_auto_row = pair(field_box("Room below lowest", self.below_in, tip=wrap_tip(ROOM_TIP)),
                               field_box("Fill sheet", self.fill_grid, tip=wrap_tip(FILL_TIP)))
        sub.addWidget(self.z_auto_row)                # shown only under Auto (_update_enabled)
        self.z_auto_hint = Hint(Z_AUTO_HINT)
        sub.addWidget(self.z_auto_hint)
        self.z_min = _spin(-1.0e6, 1.0e6, 1, 10.0, " ft")
        self.z_max = _spin(-1.0e6, 1.0e6, 1, 10.0, " ft")
        self.z_range_row = pair(field_box("Lowest", self.z_min), field_box("Highest", self.z_max))
        sub.addWidget(self.z_range_row)               # shown only under Manual (_update_enabled)

        # Sheet: Size | Format (0.3.7, the amendment of D8: the Size list has a check box per sheet size and Custom;
        # Printers take is gone), Orientation, Title
        sub = g.add_subsection("Sheet")
        self.sheet = SheetSizeCombo(SIZE_ITEMS, SIZE_CUSTOM, SIZE_FOOT, size_text)
        self.fmt = _combo(FORMAT_CHOICES, elide=True)
        self.sheet_row = pair(field_box("Size", self.sheet, tip=wrap_tip(SIZE_TIP)), field_box("Format", self.fmt))
        sub.addWidget(self.sheet_row)
        # every sheet landscape or portrait, or Auto as before (0.3.5; off with a custom page, see _update_enabled)
        self.orientation = _segmented(ORIENT_CHOICES, ORIENT_TIPS)
        sub.addWidget(field_box("Orientation", self.orientation))
        self.title_text = QLineEdit()
        self.title_text.setPlaceholderText("Optional (project, site…)")
        sub.addWidget(field_box("Title", self.title_text))
        self.export_readout = _readout()
        sub.addWidget(self.export_readout)
        self.grp_export = g
        return g

    def _build_style_group(self) -> QWidget:
        g = self._section("Sheet style", "style", "xsectionsStyleGroup")
        defaults = Settings()
        # Grid: Green | Gray (presets) | Custom (a small table), one muted legend line of the lines in use, and its
        # spacing (from the scale, or typed: moved here from Scale & sheet in 0.3.6; the fill went to Scale & sheet ›
        # Elevations in 0.3.7)
        sub = g.add_subsection("Grid")
        self.grid_color = _segmented([("Green", "green"), ("Gray", "gray"), ("Custom", "custom")],
                                     ["Green engineering pad (the default)", "Gray, for black-and-white printers",
                                      "Your own colors, widths and line styles"])
        sub.addWidget(field_box("Look", self.grid_color))
        self.grid_info = _note(self._grid_info_text("green"))       # (always shown: 0.3.7, under Custom too)
        self.grid_info.setTextFormat(Qt.TextFormat.RichText)
        sub.addWidget(self.grid_info)
        sub.addWidget(self._build_custom_grid())
        self.grid_auto = _cbox("Spacing from the scale (1 in, 0.1 in)", "Major grid every paper inch, minor every "
                                                                        "0.1 in")
        sub.addWidget(self.grid_auto)
        self.h_major = _spin(0.001, 1.0e7, 2, 10.0)
        self.h_minor = _spin(0.001, 1.0e7, 2, 1.0)
        self.v_major = _spin(0.001, 1.0e7, 2, 5.0)
        self.v_minor = _spin(0.001, 1.0e7, 2, 1.0)
        for s, tip in ((self.h_major, "Major spacing, ft"), (self.v_major, "Major spacing, ft"),
                       (self.h_minor, "Minor spacing, ft"), (self.v_minor, "Minor spacing, ft")):
            s.setToolTip(tip)
        self.grid_spacing_row = pair(field_box("Horizontal, ft", hrow(self.h_major, "/", self.h_minor, spacing=4)),
                                     field_box("Vertical, ft", hrow(self.v_major, "/", self.v_minor, spacing=4)))
        sub.addWidget(self.grid_spacing_row)          # shown only while the spacing is typed (_update_enabled)

        # Depth lines: the widths of the exploration lines (0.3.4), Reset in the heading
        self.btn_lw_reset = link_button("Reset", "Back to 0.75 pt and 1.6 pt")
        self.btn_lw_reset.setFont(_px_font(self.btn_lw_reset.font(), 11.0, W.MEDIUM))
        sub = g.add_subsection("Depth lines", [self.btn_lw_reset])
        self.depth_lw_head = sub.heading
        lo, hi = DEPTH_LW_LIMITS["depth_lw_black"]
        self.depth_lw_black = _spin(lo, hi, 2, 0.05, " pt")
        self.depth_lw_black.setToolTip("Width of black and gray depth lines")
        lo, hi = DEPTH_LW_LIMITS["depth_lw_color"]
        self.depth_lw_color = _spin(lo, hi, 2, 0.05, " pt")
        self.depth_lw_color.setToolTip("Width of colored depth lines")
        self.depth_lw_black.setValue(defaults.depth_lw_black)
        self.depth_lw_color.setValue(defaults.depth_lw_color)
        sub.addWidget(pair(field_box("Black & gray", self.depth_lw_black), field_box("Color", self.depth_lw_color)))
        self.depth_lw_hint = Hint(DEPTH_LW_HINT)
        sub.addWidget(self.depth_lw_hint)

        # Page: the printer edge and what the sheet carries
        sub = g.add_subsection("Page")
        self.edge_margin = _segmented(EDGE_CHOICES, EDGE_TIPS)
        _set_combo_data(self.edge_margin, _edge_choice(defaults.edge_margin_in))
        self.edge_margin.setToolTip("Clear strip kept at the paper edge, where printers cannot print. Most laser "
                                    "printers print to within 0.25 in; check yours before choosing 0.3 in")
        sub.addWidget(pair(field_box("Printer edge", self.edge_margin), None, (5, 4)))
        self.compact_layout = _cbox("Compact layout", "Title on one line, end letters just above the frame, two short "
                                    "note lines beside the scale bar, the elevation title on the left only")
        self.compact_layout.setChecked(defaults.compact_layout)
        self.show_notes = _cbox("Notes", "Scales, grid and data sources under the section. Unticked, the grid, "
                                "graphic scales, axis labels and title stay")
        self.show_notes.setChecked(defaults.show_notes)
        self.show_bends = _cbox("Bend lines", "A dashed vertical line and BEND label at each bend of the section line")
        self.show_bends.setChecked(defaults.show_bends)
        self.shade_below = _cbox("Shade below ground", "Shade below the ground line")
        sub.addWidget(checkbox_grid([self.compact_layout, self.show_notes, self.show_bends, self.shade_below]))
        self.style_hint = Hint(STYLE_HINT)
        sub.addWidget(self.style_hint)
        self.grp_style = g
        return g

    def _build_custom_grid(self) -> QWidget:
        """Sheet style › Grid: Custom: Major / Minor x Color, Width, Line (Solid | Dashed | Dotted | None), a
        _GridTable, then the spacing note (Verbose) and "Start from Green · Gray" at the right (the mockup's table)."""
        box = self.grid_custom_box = QWidget()
        outer = QVBoxLayout(box)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        rows = []
        for part in ("major", "minor"):
            word = part.capitalize()
            lab = QLabel(word)
            lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            color = _GridColorButton()                    # (a QgsColorButton, dimmed while its lines are None)
            color.setShowMenu(False)
            color.setAllowOpacity(False)
            color.setFixedSize(30, 24)
            color.setColorDialogTitle(f"{word} grid color")
            color.setToolTip(f"{word} grid color")
            width = _spin(GRID_W_MIN, GRID_W_MAX, 2, 0.05, " pt")
            width.setToolTip(f"{word} grid width")
            width.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            width.setMinimumWidth(70)
            style = _segmented(GRID_LINE_STYLES, GRID_LINE_TIPS)
            for i, (_text, v) in enumerate(GRID_LINE_STYLES):
                if v in LINE_STYLE_ICONS:                  # (None: a text button)
                    style.setItemIcon(i, LINE_STYLE_ICONS[v], QSize(*LINE_STYLE_ICON_SIZE))
            style.setToolTip(f"{word} grid line style")
            style.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            rows.append((lab, color, width, style))
            setattr(self, f"grid_{part}_color", color)
            setattr(self, f"grid_{part}_width", width)
            setattr(self, f"grid_{part}_style", style)
        self.grid_table = _GridTable(rows)
        outer.addWidget(self.grid_table)
        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(3)
        self.grid_spacing_note = Hint(GRID_SPACING_AUTO)            # (Verbose; its text follows the spacing)
        self.btn_grid_from_green = link_button("Green", "Start from the Green grid")
        self.btn_grid_from_gray = link_button("Gray", "Start from the Gray grid")
        fl.addWidget(self.grid_spacing_note, 1)
        fl.addStretch(0)                         # (the links stay at the right while the note is hidden)
        for w in (_muted("Start from"), self.btn_grid_from_green, _muted("·"), self.btn_grid_from_gray):
            fl.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        foot.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        outer.addWidget(foot)
        box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        box.hide()
        return box

    @staticmethod
    def _grid_custom_text(major_style: str, minor_style: str) -> str:
        """The legend line under Custom (0.3.7, D5): "Major: dashed · Minor: none", and "· no grid" with both None."""
        def word(style: str) -> str:
            return GRID_STYLE_WORDS.get(style, GRID_STYLE_WORDS["solid"])
        text = f"Major: {word(major_style)} · Minor: {word(minor_style)}"
        return text + (" · no grid" if major_style == minor_style == "none" else "")

    @staticmethod
    def _grid_info_text(preset: str) -> str:
        """The muted line under Green / Gray (the mockup's legend line): its major and minor colours and widths and
        the line style."""
        key = preset if preset in GRID_PRESETS else "green"
        (maj_c, maj_w, maj_s), (min_c, min_w, _min_s) = GRID_PRESETS[key]
        words = {"solid": "solid", "dash": "dashed", "dot": "dotted"}
        return (f'<span style="color:{maj_c}">━━</span> Major {fmt_num(maj_w)} pt &nbsp;&nbsp; '
                f'<span style="color:{min_c}">──</span> Minor {fmt_num(min_w)} pt &nbsp;&nbsp; '
                f'{words.get(maj_s, maj_s)}')

    # ---- Sheet style behaviour (the grid presets, Custom, the depth line widths)
    def _set_custom_grid(self, spec) -> None:
        """The six Custom widgets from ((major colour, width, style), (minor ...)). Silent only inside _quiet()."""
        for part, (color, width, style) in zip(("major", "minor"), spec):
            c = QColor(color)
            getattr(self, f"grid_{part}_color").setColor(c if c.isValid() else QColor(GRID_PRESETS["green"][0][0]))
            getattr(self, f"grid_{part}_width").setValue(float(width))
            seg = getattr(self, f"grid_{part}_style")
            if not _set_combo_data(seg, style):
                _set_combo_data(seg, "solid")

    def _sync_grid_ui(self, *args) -> None:
        """The legend line (the preset's under Green / Gray; 0.3.7: under Custom the line styles in words), the Custom
        table (a None part's colour and width grayed: those lines are not drawn; its swatch dimmed, _GridColorButton),
        and the spacing note (a Verbose hint: the automatic spacing, or the one typed below)."""
        v = self.grid_color.currentData()
        custom = v == "custom"
        self.grid_custom_box.setHidden(not custom)
        self.grid_info.setHidden(False)
        styles = {part: getattr(self, f"grid_{part}_style").currentData() or "solid" for part in ("major", "minor")}
        for part, style in styles.items():
            for w in (getattr(self, f"grid_{part}_color"), getattr(self, f"grid_{part}_width")):
                w.setEnabled(style != "none")
        self.grid_info.setText(self._grid_custom_text(styles["major"], styles["minor"]) if custom
                               else self._grid_info_text(v))
        self.grid_spacing_note.setText(GRID_SPACING_AUTO if self.grid_auto.isChecked() else GRID_SPACING_MANUAL)

    def _on_grid_preset(self, *args) -> None:
        """Green, Gray or Custom chosen. The first Custom of a project starts from the preset in use; later ones (and
        Green / Gray) leave the Custom values as they are."""
        v = self.grid_color.currentData()
        if v == "custom" and not self._grid_custom_used and not self._applying:
            with self._quiet():
                self._set_custom_grid(GRID_PRESETS[self._grid_last_preset])   # the first time: the preset in use
            self._grid_custom_used = True
        elif v in GRID_PRESETS:
            self._grid_last_preset = v
        self._sync_grid_ui()

    def _grid_start_from(self, preset: str) -> None:
        """Start from Green / Gray: the Custom values of that preset (one save and one rebuild)."""
        with self._quiet():
            self._set_custom_grid(GRID_PRESETS[preset])
        self._grid_custom_used = True
        self._mark_user()

    def _reset_depth_widths(self) -> None:
        """Depth lines > Reset: 0.75 pt and 1.6 pt (one save and one rebuild)."""
        with self._quiet():
            self.depth_lw_black.setValue(DEPTH_LW_BLACK)
            self.depth_lw_color.setValue(DEPTH_LW_COLOR)
        self._mark_user()

    def _spin_value(self, spin, key: str) -> float:
        """A width box's value; the stored value when the box shows it rounded (a stored 0.333 reads 0.33)."""
        v = float(spin.value())
        stored = getattr(self._settings, key, None)
        if isinstance(stored, (int, float)) and not isinstance(stored, bool) \
                and abs(float(stored) - v) <= 0.5 * 10.0 ** -spin.decimals() + 1e-9:
            return float(stored)
        return v

    # ---- theme (light: navy bars; dark: the palette's highlight)
    def _apply_theme(self) -> None:
        t = theme_for(self.palette())
        key = (t.dark, t.bar.name(), t.ink.name(), t.field.name(), t.muted.name(), t.field_ink.name(),
               t.disabled.name())
        if key == self._theme_key:
            return
        self._theme_key = key
        self._theme = t
        w = self.widget()
        if w is not None:
            w.setStyleSheet(panel_stylesheet(t, plain_text=True))
        for sec in self.sections:
            sec.header.update()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange) and not self._in_theme:
            self._in_theme = True
            try:
                self._apply_theme()
            finally:
                self._in_theme = False

    def _warn_color(self) -> str:
        return self._theme.warn.name()

    def _error_color(self) -> str:
        return self._theme.error.name()

    # ---- open / closed sections (never saved)
    def collapse_all(self) -> None:
        """Every section closed, the pills folded, surface and point-row editors closed (the ground's open while
        there is no DEM), every exploration row back on its Layer tab, the check card and an option popup closed."""
        self.opt_grid.close_popup()
        for sec in self.sections:
            sec.setCollapsed(True)
        for d in self._disclosures:
            d.setExpanded(False)
        for row in self.surface_rows:
            row.set_editor_open(False)
        for row in self.explo_rows + self.other_rows:
            row.set_editor_open(False)
        for row in self.explo_rows:
            row.tabs.setCurrentIndex(0)
        self.ground_row.set_editor_open(self.dem_layer.currentLayer() is None)
        self.card_host.close()

    def _close_card(self, *args) -> None:
        """The check card goes (the panel scrolled, a section opened or closed)."""
        self.card_host.close()

    # ---- Explorations' option buttons (0.3.7, D1, D2)
    def _on_popup_toggled(self, index: int, opened: bool) -> None:
        """A popup opened near the bottom of the view scrolls into it (once it is placed)."""
        if opened:
            QTimer.singleShot(0, functools.partial(self._show_popup, index))

    def _show_popup(self, index: int) -> None:
        """The open popup into view, POPUP_VIEW_MARGIN px from its edges; one taller than the view (a short dock)
        with its top there instead (0.3.7 fix: scrolled the usual way, Qt centres it and cuts off its header; the
        rest is reached with the scroll bar or the wheel, which keep it open)."""
        try:
            pop = self.opt_grid.current()
            if self.opt_grid.current_index() != index or pop is None:
                return
            m = POPUP_VIEW_MARGIN
            bar = self.scroll.verticalScrollBar()
            view_h = self.scroll.viewport().height()
            top = pop.mapTo(self.content, QPoint(0, 0)).y()
            if pop.height() + 2 * m > view_h:
                shown = top - bar.value()
                if shown < 0 or shown + pop.height() > view_h:      # (whole in the view already: left as it is)
                    bar.setValue(top - m)
            else:
                self.scroll.ensureWidgetVisible(pop, 0, m)
        except RuntimeError:                    # (the panel is going away)
            pass

    def _sync_option_summaries(self, *args) -> None:
        """The four buttons' summaries from their widgets (and the Plotted list's counts); the Plotted popup's title
        tells the whole count (PlottedList.text())."""
        self.opt_all.setSummary(all_layers_summary(self.tolerance.value(), bool(self.label_dir.currentData()),
                                                   bool(self.label_text.currentData())))
        self.opt_depths.setSummary(depths_summary(self.depth_line.isChecked(), self.td_label.isChecked(),
                                                  self.top_mode.currentData()))
        self.opt_water.setSummary(water_summary(self.screens.isChecked(), self.wl_label.currentData()))
        self.opt_plotted.setSummary(plotted_summary(self.plotted.counts()))
        self.pop_plotted.title_label.setToolTip(self.plotted.text())

    # ---- Verbose (0.3.6, D13: per user, never in the project)
    def _on_verbose_toggled(self, on: bool) -> None:
        """The ⋯ menu's Verbose: every Hint and readout follows (widgets.verbose_hub)."""
        W.set_verbose(bool(on))

    def _on_verbose_changed(self, on: bool) -> None:
        """Verbose changed elsewhere (another panel, a test): the menu item follows, silently."""
        try:
            self.act_verbose.blockSignals(True)
            self.act_verbose.setChecked(bool(on))
            self.act_verbose.blockSignals(False)
        except RuntimeError:                    # (the panel is going away)
            pass

    # ================================================================ point-layer rows
    @property
    def explo_rows(self) -> List[ExplorationRow]:
        """The exploration rows, in panel order (read only: rows are managed through explo_list)."""
        return self.explo_list.rows

    @property
    def other_rows(self) -> List[OtherPointsRow]:
        """The Other points rows, in panel order."""
        return self.other_list.rows

    def _new_explo_row(self) -> ExplorationRow:
        """explo_list's row factory: a row whose user's layer choice may take its left-off entries along."""
        row = ExplorationRow()
        row.layerSwapped.connect(self._on_layer_swapped)
        return row

    def _new_other_row(self) -> OtherPointsRow:
        row = OtherPointsRow()
        row.set_end_labels(*self._end_labels())
        return row

    def _end_labels(self) -> Tuple[str, str]:
        """The section's end labels with primes (A, A′), for the Other points hints."""
        return pretty_label(self.start_label.text().strip()), pretty_label(self.end_label.text().strip())

    def _set_explo_rows(self, rows: Sequence[dict], guess: bool = False) -> None:
        self.explo_list.set_rows(rows, guess=guess)

    def _append_explo_row(self, d: Optional[dict] = None, open_editor: bool = False,
                          guess: bool = False) -> ExplorationRow:
        return self.explo_list.append(d, open_editor=open_editor, guess=guess)

    def _set_other_rows(self, rows: Sequence[dict], guess: bool = False) -> None:
        self.other_list.set_rows(rows, guess=guess)

    def _append_other_row(self, d: Optional[dict] = None, open_editor: bool = False,
                          guess: bool = False) -> OtherPointsRow:
        return self.other_list.append(d, open_editor=open_editor, guess=guess)

    def move_explo_row(self, row: ExplorationRow, step: int) -> None:
        self.explo_list.move(row, step)

    def remove_explo_row(self, row: ExplorationRow) -> None:
        """Remove a row (the ⋯ menu). The last one removed leaves a ground line only (kept when layers are added)."""
        self.explo_list.remove(row)

    def move_other_row(self, row: OtherPointsRow, step: int) -> None:
        self.other_list.move(row, step)

    def remove_other_row(self, row: OtherPointsRow) -> None:
        self.other_list.remove(row)

    def _point_layers(self, among: Optional[Sequence[Any]] = None) -> List[QgsVectorLayer]:
        """The valid point layers in the order of the layers panel, then any not in it (in mapLayers() order, or in
        the order of `among`); only those of `among` when it is given (layers just added are not in the panel
        yet)."""
        return self._layers_of(("point",), among)

    def _feature_layers(self, among: Optional[Sequence[Any]] = None) -> List[QgsVectorLayer]:
        """The valid point, line and polygon layers (core.others.feature_kind), as _point_layers orders them (0.3.6:
        the layers an Other features row may draw)."""
        return self._layers_of(("point", "line", "polygon"), among)

    @staticmethod
    def _layers_of(kinds: Sequence[str], among: Optional[Sequence[Any]] = None) -> List[QgsVectorLayer]:
        prj = QgsProject.instance()
        out: List[QgsVectorLayer] = []
        seen = set()

        def take(lyr) -> None:
            if isinstance(lyr, QgsVectorLayer) and feature_kind(lyr) in kinds and lyr.id() not in seen:
                seen.add(lyr.id())
                out.append(lyr)

        wanted = None if among is None else {l.id() for l in among if isinstance(l, QgsVectorLayer)}
        try:
            for node in prj.layerTreeRoot().findLayers():
                lyr = node.layer()
                if wanted is None or (lyr is not None and lyr.id() in wanted):
                    take(lyr)
        except Exception:
            pass
        for lyr in (prj.mapLayers().values() if among is None else among):
            take(lyr)
        return out

    def _used_point_ids(self) -> set:
        return {r.stored()["layer_id"] for r in self.explo_rows + self.other_rows} - {""}

    def _default_point_layer(self, hint) -> Optional[QgsVectorLayer]:
        """The first point layer no row uses (layer order, those named like `hint` first), else the first point
        layer (None without any)."""
        layers = self._point_layers()
        used = self._used_point_ids()
        free = [l for l in layers if l.id() not in used]
        cands = [l for l in free if hint(l.name())] + free + layers
        return cands[0] if cands else None

    def add_point_layer(self, layer: Optional[QgsVectorLayer] = None, open_editor: bool = True) -> ExplorationRow:
        """+ Add point layer (Explorations): a row for `layer` (default: _default_point_layer, explorations' names
        first), its fields guessed, in or out of the elevation range by its name and fields, its editor open."""
        if layer is None:
            layer = self._default_point_layer(is_point_hint)
        d = dict(POINT_LAYER_DEFAULTS, layer_id=layer.id() if layer is not None else "")
        if layer is not None:
            d["in_range"] = guess_in_range(layer.name(), layer.fields().names())
        row = self._append_explo_row(d, open_editor=open_editor, guess=True)
        self._mark_user()
        return row

    def _default_feature_layer(self) -> Optional[QgsVectorLayer]:
        """+ Add layer (Other features)'s layer (0.3.6): the valid point, line and polygon layers (layer order) that no
        row uses, but the section line's and the "XSections lines" layer: those named like seeps or springs first,
        then free point layers, then the other free layers; else the first point layer (None without any)."""
        line = self.line_layer.currentLayer()
        used = self._used_point_ids() | ({line.id()} if line is not None else set())
        free = [l for l in self._feature_layers()
                if l.id() not in used and not l.customProperty(LINES_LAYER_PROP, False)]
        points = self._point_layers()
        cands = ([l for l in free if is_other_hint(l.name())] + [l for l in free if feature_kind(l) == "point"]
                 + free + points)
        return cands[0] if cands else None

    def add_other_points(self, layer: Optional[QgsVectorLayer] = None, open_editor: bool = True) -> OtherPointsRow:
        """+ Add layer (Other features): a row for `layer` (default: _default_feature_layer) of its kind
        (model.feature_row: a point, line or polygon row), its fields guessed, its editor open."""
        if layer is None:
            layer = self._default_feature_layer()
        d = feature_row(feature_kind(layer) or "point", layer_id=layer.id() if layer is not None else "")
        row = self._append_other_row(d, open_editor=open_editor, guess=True)
        self._mark_user()
        return row

    def _on_rows_edited(self, *args) -> None:
        """A user's edit, move or remove in either row list."""
        self._update_enabled()
        prj = QgsProject.instance()
        wanted = {lid for lid in self._tracked_ids() if prj.mapLayer(lid) is not None}
        # (a layer already tracked through an Other points row or as a water-level table, then picked in an
        # exploration row, changes no id: its styleChanged is missing)
        style_ids = {lid for lid in self._explo_layer_ids() if prj.mapLayer(lid) is not None}
        have = {(lid, name) for lid, name, _slot in self._layer_conns}
        if wanted != {lid for lid, _name, _slot in self._layer_conns} or any((lid, "styleChanged") not in have
                                                                            for lid in style_ids):
            self._track_layer_signals()                  # a layer or table chosen in a row
        self._on_widget_changed()

    def _on_rows_changed(self, *args) -> None:
        """Rows added, moved or removed (by the user or in code): numbering, enabling, end labels, layer signals."""
        a, b = self._end_labels()
        for row in self.other_rows:
            row.set_end_labels(a, b)
        self._update_enabled()
        self._track_layer_signals()
        self._update_problems()

    def _on_explo_emptied(self) -> None:
        self._points_none = True                         # he removed the last row: a ground line only

    def _on_other_emptied(self) -> None:
        self._others_none = True

    def _on_end_labels_edited(self, *args) -> None:
        a, b = self._end_labels()
        for row in self.other_rows:
            row.set_end_labels(a, b)

    def _rekey_hidden(self, old_id: str, new_id: str) -> None:
        """The same layer added again (a new id, the same features): its left-off entries follow it, on every line."""
        if not old_id or not new_id or old_id == new_id:
            return
        out = set()
        for e in self._hidden:
            line, lid, fid = e.rsplit("|", 2)
            out.add(f"{line}|{new_id if lid == old_id else lid}|{fid}")
        self._hidden = sorted(out)

    def _on_layer_swapped(self, old_id: str, new_id: str, old_name: str) -> None:
        """The user chose another layer in a row. When the row's layer was missing and the new one has its name (the
        same layer added again), his left-off entries go with it; never for a layer of another name."""
        if not old_id or point_layer(old_id) is not None or not old_name:
            return
        lyr = point_layer(new_id)
        if lyr is not None and lyr.name() == old_name:
            self._rekey_hidden(old_id, new_id)

    # ---- the left-off list (Plotted explorations)
    def _on_plotted_toggled(self, layer_id: str, fid: int, plotted: bool) -> None:
        """A tick in Plotted explorations: left off (or back on) this section line, the line the list shows."""
        if self._applying:
            return
        lk = self.model.line_key if self.model is not None else line_key(self.settings())
        if not lk:
            return
        key = hidden_key(lk, layer_id, fid)
        before = list(self._hidden)
        entries = set(self._hidden)
        if plotted:
            entries.discard(key)
        else:
            entries.add(key)
        self._hidden = sorted(entries)
        if self._hidden != before:
            self._on_widget_changed()

    def show_all_plotted(self) -> None:
        """Show all: every exploration left off this section line is plotted again (other lines keep theirs)."""
        if self._applying:
            return
        lk = self.model.line_key if self.model is not None else line_key(self.settings())
        before = list(self._hidden)
        self._hidden = [e for e in self._hidden if e.rsplit("|", 2)[0] != lk]
        if self._hidden != before:
            self._on_widget_changed()

    def _hidden_of(self, lk: str) -> List[str]:
        """The left-off entries of one line, as (layer id, fid) parts: "LAYERID|FID"."""
        return [e.split("|", 1)[1] for e in self._hidden if lk and e.rsplit("|", 2)[0] == lk]

    def _copy_hidden(self, old_lk: str, new_lk: str, replace: bool = True) -> None:
        """Give line `new_lk` the left-off entries of `old_lk` (copied; `replace`: exactly those, its own dropped)."""
        if not old_lk or not new_lk or old_lk == new_lk:
            return
        keep = [e for e in self._hidden if not (replace and e.rsplit("|", 2)[0] == new_lk)]
        self._hidden = sorted(set(keep) | {f"{new_lk}|{rest}" for rest in self._hidden_of(old_lk)})

    def _drop_hidden(self, lk: str) -> None:
        self._hidden = [e for e in self._hidden if e.rsplit("|", 2)[0] != lk]

    # ================================================================ signals
    def _connect_widgets(self) -> None:
        ch = self._on_widget_changed
        # section line
        self.line_layer.layerChanged.connect(self._on_line_layer_changed)
        self.line_layer.activated.connect(self._on_line_layer_activated)
        self.line_feature.currentIndexChanged.connect(lambda _i: self._schedule())
        self.line_feature.activated.connect(self._on_feature_activated)
        self.btn_pick.toggled.connect(self._on_pick_toggled)
        self.btn_draw.toggled.connect(self._on_draw_toggled)
        self.btn_selected.clicked.connect(self.use_selected)
        self.btn_reverse.clicked.connect(self.reverse_line)
        self.btn_save_line.clicked.connect(self.save_line_to_layer)
        self.act_save_line.triggered.connect(self.save_line_to_layer)
        self.start_label.textChanged.connect(ch)
        self.end_label.textChanged.connect(ch)
        self.start_label.textChanged.connect(self._on_end_labels_edited)
        self.end_label.textChanged.connect(self._on_end_labels_edited)
        # surfaces (the ground and the others)
        self.dem_layer.layerChanged.connect(self._on_dem_layer_changed)
        self.dem_layer.activated.connect(self._mark_user)
        self.dem_band.bandChanged.connect(ch)
        self.dem_band.bandChanged.connect(self._update_ground_row)
        # (the ground row's name area opens and closes its editor by itself: GroundRow)
        self.btn_add_surface.clicked.connect(lambda: self.add_surface())
        self._bands_menu.aboutToShow.connect(self._fill_bands_menu)
        self.btn_add_mf6.clicked.connect(lambda: self.add_mf6())
        self.z_units.currentIndexChanged.connect(ch)
        self.datum.textChanged.connect(ch)
        # explorations (rows: a user's edit, move or remove in a row list marks the user; rows made in code do not)
        for lst, emptied in ((self.explo_list, self._on_explo_emptied), (self.other_list, self._on_other_emptied)):
            lst.changed.connect(self._on_rows_edited)
            lst.rowsChanged.connect(self._on_rows_changed)
            lst.emptied.connect(emptied)
            lst.checksChanged.connect(self._update_counts)       # a row's badge came, went or changed
        self.btn_add_points.clicked.connect(lambda: self.add_point_layer())
        self.btn_add_other.clicked.connect(lambda: self.add_other_points())
        self.plotted.toggled.connect(self._on_plotted_toggled)
        self.plotted.toggled.connect(self._sync_option_summaries)       # (after: the count of the tick)
        self.plotted.showAllRequested.connect(self.show_all_plotted)
        self.tolerance.valueChanged.connect(ch)
        self.label_text.currentIndexChanged.connect(ch)
        self.label_dir.currentIndexChanged.connect(ch)
        self.btn_csv.triggered.connect(self.export_points_csv)
        # depths
        self.depth_line.toggled.connect(ch)
        self.depth_line.toggled.connect(self._update_enabled)
        self.top_mode.currentIndexChanged.connect(ch)
        self.top_mode.currentIndexChanged.connect(self._update_enabled)
        self.zero_missing.toggled.connect(ch)
        self.top_max_diff.valueChanged.connect(ch)
        self.td_label.toggled.connect(ch)
        # screens and water levels (their fields are in the rows)
        self.screens.toggled.connect(ch)
        self.screens.toggled.connect(self._update_enabled)
        self.wl_label.currentIndexChanged.connect(ch)
        # the option buttons' summaries follow every change (0.3.7, D1)
        for sig in (self.tolerance.valueChanged, self.label_dir.currentIndexChanged,
                    self.label_text.currentIndexChanged, self.top_mode.currentIndexChanged,
                    self.wl_label.currentIndexChanged, self.depth_line.toggled, self.td_label.toggled,
                    self.screens.toggled):
            sig.connect(self._sync_option_summaries)
        # export
        self.h_scale.editTextChanged.connect(self._on_scale_changed)
        self.v_scale.editTextChanged.connect(self._on_scale_changed)
        self.grid_auto.toggled.connect(self._on_grid_auto_toggled)
        for s in (self.h_major, self.h_minor, self.v_major, self.v_minor, self.z_min, self.z_max, self.below_in):
            s.valueChanged.connect(ch)
        self.z_mode.currentIndexChanged.connect(ch)
        self.z_mode.currentIndexChanged.connect(self._update_enabled)
        self.distance_labels.currentIndexChanged.connect(ch)
        self.sheet.checksChanged.connect(ch)                    # (0.3.7: the Size list's check boxes)
        self.sheet.checksChanged.connect(self._update_enabled)
        self.orientation.currentIndexChanged.connect(ch)
        self.tile.toggled.connect(ch)
        self.fmt.currentIndexChanged.connect(ch)
        self.title_text.textChanged.connect(ch)
        # style
        self.grid_color.currentIndexChanged.connect(self._on_grid_preset)      # (before ch: the first Custom)
        self.grid_color.currentIndexChanged.connect(ch)
        for part in ("major", "minor"):
            getattr(self, f"grid_{part}_color").colorChanged.connect(ch)
            getattr(self, f"grid_{part}_width").valueChanged.connect(ch)
            getattr(self, f"grid_{part}_style").currentIndexChanged.connect(ch)
            getattr(self, f"grid_{part}_style").currentIndexChanged.connect(self._sync_grid_ui)   # (None: grayed)
        self.btn_grid_from_green.clicked.connect(lambda: self._grid_start_from("green"))
        self.btn_grid_from_gray.clicked.connect(lambda: self._grid_start_from("gray"))
        self.depth_lw_black.valueChanged.connect(ch)
        self.depth_lw_color.valueChanged.connect(ch)
        self.btn_lw_reset.clicked.connect(self._reset_depth_widths)
        self.shade_below.toggled.connect(ch)
        self.show_bends.toggled.connect(ch)
        self.compact_layout.toggled.connect(ch)
        self.edge_margin.currentIndexChanged.connect(ch)
        self.show_notes.toggled.connect(ch)
        self.fill_grid.currentIndexChanged.connect(ch)
        # bottom
        self.btn_refresh.clicked.connect(self.reload)
        self.btn_export.clicked.connect(self.export_section)
        self.act_verbose.toggled.connect(self._on_verbose_toggled)
        # the check card closes when the panel scrolls or a section opens or closes (0.3.6)
        self.scroll.verticalScrollBar().valueChanged.connect(self._close_card)
        for sec in self.sections:
            sec.collapsedStateChanged.connect(self._close_card)
        # layers added to / removed from the project later, the project CRS, the project being written (Save As:
        # model paths relative to its new place) (disconnected in cleanup)
        prj = QgsProject.instance()
        prj.layersAdded.connect(self._on_layers_added)
        prj.layersWillBeRemoved.connect(self._on_layers_will_be_removed)
        prj.layersRemoved.connect(self._on_layers_removed)
        prj.crsChanged.connect(self._on_project_crs_changed)
        prj.writeProject.connect(self._on_write_project)

    @contextlib.contextmanager
    def _quiet(self):
        """Programmatic widget changes: no 'user changed' flag, no scheduled save."""
        self._applying += 1
        try:
            yield
        finally:
            self._applying -= 1

    def _on_widget_changed(self, *args) -> None:
        if self._applying:
            return
        self._user_changed = True
        self._schedule()

    def _mark_user(self, *args) -> None:
        self._user_changed = True
        self._schedule()

    def _schedule(self, *args) -> None:
        self._stale = True
        if not self._applying:
            self._timer.start()
            self._update_chips()

    def _on_timer(self) -> None:
        if self._user_changed:
            self.save_settings()
        if self.isVisible():
            self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._was_closed:              # closed -> open: every section starts closed again
            self._was_closed = False
            self.collapse_all()
        self.feedback.set_visible(True)
        if self._stale:
            self._timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.card_host.close()
        self.opt_grid.close_popup()
        if self.isHidden():               # closed or toggled off (not merely behind another dock tab)
            self._was_closed = True
            self._hide_cursor()

    def _on_closed_state_changed(self, closed: bool) -> None:
        if closed:
            self._hide_cursor()
        self.feedback.set_visible(not closed)

    # ================================================================ settings <-> widgets
    def settings(self) -> Settings:
        """A Settings built from the widgets."""
        s = Settings()
        data = self.line_feature.currentData()
        layer = self.line_layer.currentLayer()
        if data == DRAWN and self._drawn_wkt:
            s.line_wkt, s.line_crs_authid = self._drawn_wkt, self._drawn_crs
        elif layer is not None and data is not None and data != DRAWN:
            s.line_layer_id, s.line_fid = layer.id(), int(data)
        s.start_label = self.start_label.text().strip()
        s.end_label = self.end_label.text().strip()

        dem = self.dem_layer.currentLayer()
        s.dem_layer_id = dem.id() if dem is not None else ""
        s.dem_band = max(1, self.dem_band.currentBand()) if dem is not None else 1
        s.dem_z_units = self.z_units.currentData()
        s.vertical_datum = self.datum.text().strip()
        s.surfaces = [row.value() for row in self.surface_rows]

        # the point-layer rows (a row whose layer is missing writes back what it was given); the flat per-layer keys
        # stay at their defaults
        s.point_layers = self.explo_list.values()
        s.other_points = self.other_list.values()
        s.hidden_points = sorted(self._hidden)
        s.tolerance_ft = self.tolerance.value()
        s.label_offset = bool(self.label_text.currentData())
        s.label_vertical = bool(self.label_dir.currentData())

        s.depth_line = self.depth_line.isChecked()
        s.top_mode = self.top_mode.currentData()
        s.top_max_diff_ft = self.top_max_diff.value()
        s.zero_is_missing = self.zero_missing.isChecked()
        s.td_label = self.td_label.isChecked()

        s.screens = self.screens.isChecked()
        s.wl_label = self.wl_label.currentData() or "off"

        s.h_scale = self.h_scale.value() or self._settings.h_scale
        s.v_scale = self.v_scale.value() or self._settings.v_scale
        s.grid_auto = self.grid_auto.isChecked()
        s.h_major, s.h_minor = self.h_major.value(), self.h_minor.value()
        s.v_major, s.v_minor = self.v_major.value(), self.v_minor.value()
        s.z_mode = self.z_mode.currentData()
        s.z_min, s.z_max = self.z_min.value(), self.z_max.value()
        s.below_in = self.below_in.value()
        s.distance_labels = self.distance_labels.currentData()
        s.sheet, s.allowed_sheets = sheet_from_checks(self.sheet.checked(), self.sheet.isCustom())   # (0.3.7)
        s.orientation = self.orientation.currentData() or "auto"
        s.tile = self.tile.isChecked()
        s.export_format, dpi = self.fmt.currentData()
        s.dpi = dpi if s.export_format == "png" else int(self._settings.dpi)
        s.title = self.title_text.text().strip()

        s.grid_color = self.grid_color.currentData()
        for part in ("major", "minor"):
            setattr(s, f"grid_{part}_color", getattr(self, f"grid_{part}_color").color().name())
            setattr(s, f"grid_{part}_width", self._spin_value(getattr(self, f"grid_{part}_width"),
                                                              f"grid_{part}_width"))
            setattr(s, f"grid_{part}_style", getattr(self, f"grid_{part}_style").currentData() or "solid")
        s.grid_custom_used = bool(self._grid_custom_used)
        s.depth_lw_black = self._spin_value(self.depth_lw_black, "depth_lw_black")
        s.depth_lw_color = self._spin_value(self.depth_lw_color, "depth_lw_color")
        s.shade_below = self.shade_below.isChecked()
        s.show_bends = self.show_bends.isChecked()
        s.compact_layout = self.compact_layout.isChecked()
        s.edge_margin_in = float(self.edge_margin.currentData())
        s.show_notes = self.show_notes.isChecked()
        s.fill_grid = self.fill_grid.currentData()
        return s

    def apply_settings(self, s: Settings, guess_fields: bool = False) -> None:
        """Show `s` in the widgets. Layers that no longer exist keep the combo's current choice; a point row whose
        layer is gone keeps every key it was given (ui.point_rows).

        The exploration rows come from layer_rows(s) (so settings with the flat single-layer keys show one row). An
        optional field left empty stays empty (the user chose none), unless `guess_fields` (fresh settings, nothing
        saved yet): then it is guessed from the field names."""
        prj = QgsProject.instance()
        with self._quiet():
            self._settings = s
            # ground
            # an empty id means "none chosen" (a fresh project with no likely DEM or section line layer);
            # an id whose layer is gone keeps the combo's current choice
            dem = prj.mapLayer(s.dem_layer_id) if s.dem_layer_id else None
            if isinstance(dem, QgsRasterLayer):
                self.dem_layer.setLayer(dem)
            elif not s.dem_layer_id:
                self.dem_layer.setLayer(None)
            self._on_dem_layer_changed(self.dem_layer.currentLayer())
            if self.dem_layer.currentLayer() is not None:
                self.dem_band.setBand(s.dem_band)
            _set_combo_data(self.z_units, s.dem_z_units)
            self.datum.setText(s.vertical_datum)
            self._set_surface_rows(s.surfaces)

            # section line (first: the left-off list and the rows' hints follow it)
            self.start_label.setText(s.start_label)
            self.end_label.setText(s.end_label)

            # explorations and other points: one row each (fields before types, in the rows), the left-off list
            self._hidden = clean_hidden(s.hidden_points)
            self._gone_lines = {}
            self._set_explo_rows(layer_rows(s), guess=guess_fields)
            self._set_other_rows(clean_other_points(s.other_points), guess=guess_fields)
            self.tolerance.setValue(s.tolerance_ft)
            _set_combo_data(self.label_text, bool(s.label_offset))
            _set_combo_data(self.label_dir, bool(s.label_vertical))

            self.depth_line.setChecked(bool(s.depth_line))
            _set_combo_data(self.top_mode, s.top_mode)
            self.top_max_diff.setValue(s.top_max_diff_ft)
            self.zero_missing.setChecked(bool(s.zero_is_missing))
            self.td_label.setChecked(bool(s.td_label))

            # screens and water levels (their fields are in the rows)
            self.screens.setChecked(bool(s.screens))
            if not _set_combo_data(self.wl_label, s.wl_label):
                _set_combo_data(self.wl_label, "off")
            self.plotted.set_entries(None)                   # until the next build

            # section line
            self._drawn_wkt, self._drawn_crs = s.line_wkt, s.line_crs_authid
            self._drawn_desc = "Drawn on map"
            self._reversed_from = None
            line_layer = prj.mapLayer(s.line_layer_id) if s.line_layer_id else None
            if not s.line_layer_id:
                self.line_layer.setLayer(None)
            if isinstance(line_layer, QgsVectorLayer):
                self.line_layer.setLayer(line_layer)
                select = s.line_fid
            elif s.line_wkt:
                select = DRAWN
            else:
                select = None
            self._fill_features(select=select)

            # scales and sheet
            self.h_scale.setValue(s.h_scale)
            self.v_scale.setValue(s.v_scale)
            self.grid_auto.setChecked(bool(s.grid_auto))
            hM, hm, vM, vm = s.effective_grid()
            self.h_major.setValue(hM)
            self.h_minor.setValue(hm)
            self.v_major.setValue(vM)
            self.v_minor.setValue(vm)
            _set_combo_data(self.z_mode, s.z_mode)
            self.z_min.setValue(s.z_min)
            self.z_max.setValue(s.z_max)
            self.below_in.setValue(s.below_in)
            _set_combo_data(self.distance_labels, s.distance_labels)
            self.sheet.setChecks(*checks_from_sheet(s.sheet, s.allowed_sheets))     # (0.3.7: the Size list)
            _set_combo_data(self.orientation, clean_orientation(s.orientation))
            self.tile.setChecked(bool(s.tile))
            if not _set_combo_data(self.fmt, (s.export_format, int(s.dpi))):
                for i in range(self.fmt.count()):
                    if self.fmt.itemData(i)[0] == s.export_format:
                        self.fmt.setCurrentIndex(i)
                        break
            self.title_text.setText(s.title)

            if not _set_combo_data(self.grid_color, s.grid_color):
                _set_combo_data(self.grid_color, "green")
            self._set_custom_grid(grid_spec(dataclasses.replace(s, grid_color="custom")))   # (cleaned)
            black, color = depth_widths(s)
            self.depth_lw_black.setValue(black)
            self.depth_lw_color.setValue(color)
            self._grid_custom_used = bool(s.grid_custom_used) or s.grid_color == "custom"
            self._grid_last_preset = s.grid_color if s.grid_color in GRID_PRESETS else "green"
            self._sync_grid_ui()
            self.shade_below.setChecked(bool(s.shade_below))
            self.show_bends.setChecked(bool(s.show_bends))
            self.compact_layout.setChecked(bool(s.compact_layout))
            _set_combo_data(self.edge_margin, _edge_choice(s.edge_margin_in))
            self.show_notes.setChecked(bool(s.show_notes))
            if not _set_combo_data(self.fill_grid, s.fill_grid):
                _set_combo_data(self.fill_grid, "off")
            self._update_enabled()
        self._track_layer_signals()
        self._schedule()
        self._update_chips()
        self._sync_option_summaries()

    def save_settings(self) -> bool:
        """Write the current settings to the project (only if they changed)."""
        self._user_changed = False
        return settings_store.save(QgsProject.instance(), self.settings())

    def _on_write_project(self, *args) -> None:
        """The project is being written (Save, Save As): store the settings again, so the model file paths are
        relative to where the project file now is (settings_store.save). A project without XSections settings
        stays without."""
        prj = QgsProject.instance()
        if self._user_changed or settings_store.stored_json(prj):
            try:
                self.save_settings()
            except Exception:                       # never in the way of saving the project
                QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Warning)

    def _on_project_crs_changed(self, *args) -> None:
        """A model surface without a model CRS of its own follows the project CRS: show which one now."""
        for row in self.surface_rows:
            if isinstance(row, ModelSurfaceRow):
                row.sync()

    def restore_from_project(self) -> None:
        """Called at start-up and whenever a project has been read."""
        s = settings_store.load(QgsProject.instance())
        self.model = self.plan = None
        # saved settings without an exploration row: the user chose a ground line only; saved settings never get
        # Other points rows by themselves either (layers added later are his to add)
        self._points_none = s is not None and not layer_rows(s)
        self._others_none = s is not None
        fresh = s is None
        if fresh:
            s = Settings()
            self._guess_layers(s)
        self.apply_settings(s, guess_fields=fresh)
        self._user_changed = False
        self.collapse_all()

    def project_cleared(self) -> None:
        self._timer.stop()
        self.model = self.plan = None
        from ..core import mf6, mf6_section          # the model files of the closed project: forget them
        mf6.clear_cache()
        mf6_section.clear_cache()
        self._drawn_wkt = self._drawn_crs = ""
        self._new_hover_section()
        self.feedback.clear()
        if self.preview is not None:
            self.preview.show_message("")
        with self._quiet():
            self.apply_settings(Settings())
        self._user_changed = False
        self._stale = True
        self._points_none = self._others_none = False
        self._hidden = []
        self._gone_lines = {}
        for lab in (self.line_readout, self.ground_readout, self.explo_readout, self.depth_readout,
                    self.screens_readout, self.other_readout, self.export_readout):
            lab.setWanted(False)
        self._set_message("")
        self._update_problems()                          # (no model: only the rows' own problems stay)
        self.collapse_all()
        self._update_chips()
        self._sync_option_summaries()

    def _guess_layers(self, s: Settings, layers: Optional[Sequence[Any]] = None) -> None:
        """Fill layer ids in a fresh Settings from layer names in the project (or among `layers`): the DEM, the
        section line, and the point-layer rows (_guess_point_rows)."""
        among = layers
        layers = list(QgsProject.instance().mapLayers().values() if layers is None else layers)

        def pick(pred, hints, fallback=None):
            cands = [l for l in layers if pred(l)]
            for hint in hints:
                for l in cands:
                    if hint in l.name().lower():
                        return l
            if fallback is None:
                return None
            return next((l for l in cands if fallback(l)), None)

        def plain_dem(l) -> bool:          # single band and not named like a photo or a hillshade
            name = l.name().lower()
            return l.bandCount() == 1 and not any(h in name for h in NOT_DEM_HINTS)

        dem = pick(lambda l: isinstance(l, QgsRasterLayer), DEM_HINTS, plain_dem)
        line = pick(lambda l: isinstance(l, QgsVectorLayer) and l.geometryType() == Qgis.GeometryType.Line
                    and not l.customProperty(LINES_LAYER_PROP, False), LINE_HINTS)
        s.dem_layer_id = dem.id() if dem else ""
        if line is not None:
            s.line_layer_id = line.id()
            first = next(line.getFeatures(QgsFeatureRequest().setLimit(1).setNoAttributes()
                                          .setFlags(Qgis.FeatureRequestFlag.NoGeometry)), None)
            s.line_fid = first.id() if first is not None else None
        s.point_layers, s.other_points = self._guess_point_rows(self._point_layers(among))

    @staticmethod
    def _guess_point_rows(layers: Sequence[QgsVectorLayer]) -> Tuple[List[dict], List[dict]]:
        """(exploration rows, Other points rows) guessed from the names of point `layers` (in layer order): a row for
        every layer named like explorations (POINT_HINTS; supply-like ones last and unticked: he ticks them on; at
        most MAX_GUESSED_ROWS), else for the first layer not named like seeps or springs; an Other points row for
        every other layer named like seeps or springs (OTHER_HINTS). Their fields are guessed when the rows are made;
        "Include in the elevation range" here (point_guess.guess_in_range)."""
        def in_range(lyr) -> bool:
            return guess_in_range(lyr.name(), lyr.fields().names())

        named = [l for l in layers if is_point_hint(l.name())]
        if not named:
            named = [l for l in layers if not is_other_hint(l.name())][:1]
        named = sorted(named, key=lambda l: not in_range(l))[:MAX_GUESSED_ROWS]      # supply-like last (stable)
        explo = [dict(POINT_LAYER_DEFAULTS, layer_id=l.id(), in_range=in_range(l), visible=in_range(l))
                 for l in named]
        used = {l.id() for l in named}
        others = [feature_row("point", layer_id=l.id()) for l in layers
                  if l.id() not in used and is_other_hint(l.name())]
        return explo, others

    def _on_layers_added(self, layers) -> None:
        """Layers added after start-up. A layer box that is still empty gets the same guess as in a fresh project
        (from the new layers only); so do the row lists while they are empty (unless he removed their last row, or
        a project was read). A missing row whose layer comes back (the same name) takes it, with its left-off
        entries. None of this marks the user (guesses are never saved by themselves)."""
        if self._applying:
            return
        prj = QgsProject.instance()
        guess = Settings()
        self._guess_layers(guess, layers)
        added = self._point_layers(layers)
        added_features = self._feature_layers(layers)            # (an Other features row: any of the three kinds)
        with self._quiet():
            if self.dem_layer.currentLayer() is None and guess.dem_layer_id:
                self.dem_layer.setLayer(prj.mapLayer(guess.dem_layer_id))
            # a line layer removed and added again (the same name, a new id, the same features): his left-off
            # entries on its lines follow it (whatever the line box then shows); never for a layer of another name
            back_line = None
            for lyr in layers or []:
                if not (isinstance(lyr, QgsVectorLayer) and lyr.geometryType() == Qgis.GeometryType.Line):
                    continue
                old = next((o for o, (name, _fid) in self._gone_lines.items()
                            if name == lyr.name() and prj.mapLayer(o) is None), None)
                if old is not None:
                    _name, fid = self._gone_lines.pop(old)
                    self._rekey_line_hidden(old, lyr.id())
                    if fid is not None and back_line is None:
                        back_line = (lyr, fid)
            if self.line_layer.currentLayer() is None and not self._drawn_wkt and back_line is not None:
                self.line_layer.setLayer(back_line[0])           # back to the line he was on
                self._fill_features(select=back_line[1])
            elif self.line_layer.currentLayer() is None and not self._drawn_wkt and guess.line_layer_id:
                self.line_layer.setLayer(prj.mapLayer(guess.line_layer_id))
            if not self.explo_rows and not self._points_none and guess.point_layers:
                self._set_explo_rows(guess.point_layers, guess=True)
            if not self.other_rows and not self._others_none and guess.other_points:
                self._set_other_rows(guess.other_points, guess=True)
            # a missing row takes its layer back: the first added layer of the name its layer had (a point layer for
            # an exploration row; a point, line or polygon layer for an Other features row)
            for row in self.explo_rows + self.other_rows:
                name = row.last_layer_name()
                if not row.is_missing() or not name:
                    continue
                pool = added_features if isinstance(row, OtherPointsRow) else added
                back = next((l for l in pool if l.name() == name), None)
                if back is not None:
                    old_id = row.stored()["layer_id"]
                    row.take_layer(back)
                    self._rekey_hidden(old_id, back.id())
            for row in self.explo_rows + self.other_rows:
                row.sync_layer()
        for row in self.surface_rows:          # a surface whose raster comes back
            row.sync_layer()
        self._update_enabled()
        self._track_layer_signals()
        self._schedule()
        self._update_chips()
        # the rows' layer boxes hear of the new layers after the dock (their models connect to layersAdded later):
        # a row that took its layer back above shows it once this signal is over (else its box stays empty and it
        # would ignore every later edit)
        self._resync_timer.start()

    def _resync_point_rows(self) -> None:
        """After layers were added: each row shows its layer again, now that every layer box has the new layers."""
        with self._quiet():
            for row in self.explo_rows + self.other_rows:
                row.sync_layer()

    def _rekey_line_hidden(self, old_id: str, new_id: str) -> None:
        """The same line layer added again (a new id, the same features): the left-off entries of its lines follow it."""
        if not old_id or not new_id or old_id == new_id:
            return
        pre = old_id + "#"
        out = set()
        for e in self._hidden:
            line, rest = e.split("|", 1)
            out.add(f"{new_id}#{line[len(pre):]}|{rest}" if line.startswith(pre) else e)
        self._hidden = sorted(out)

    def _remember_gone_lines(self, removed) -> None:
        """Line layers about to be removed (ids or layers; they still resolve) that hold left-off entries, or carry the
        line in use: their names (and that line's fid), so that the same layer added again takes the entries."""
        prj = QgsProject.instance()
        current = (self.model.line_key if self.model is not None else line_key(self._settings)) or ""
        for item in (removed if isinstance(removed, (list, tuple)) else [removed]):
            lyr = prj.mapLayer(item) if isinstance(item, str) else item
            if not (isinstance(lyr, QgsVectorLayer) and lyr.geometryType() == Qgis.GeometryType.Line):
                continue
            pre = lyr.id() + "#"
            fid = None
            if current.startswith(pre):
                try:
                    fid = int(current[len(pre):])
                except ValueError:
                    fid = None
            if fid is not None or any(e.startswith(pre) for e in self._hidden):
                self._gone_lines[lyr.id()] = (lyr.name(), fid)

    def _on_layers_will_be_removed(self, *args) -> None:
        try:
            self._remember_gone_lines(args[0] if args else ())
        except RuntimeError:                   # (a layer already half gone: nothing to remember)
            pass
        self._untrack_layer_signals()          # while the layers still exist (made again in _on_layers_removed)
        self._removing_layers = True
        # the rows' layer boxes move on by themselves: not a choice (the point rows keep every stored key)
        for row in self.surface_rows + self.explo_rows + self.other_rows:
            row.set_removing(True)

    def _on_layers_removed(self, *args) -> None:
        self._removing_layers = False
        for row in self.surface_rows + self.explo_rows + self.other_rows:
            row.set_removing(False)
        self._update_enabled()
        self._update_ground_row()
        self._update_problems()
        self._update_chips()
        self._track_layer_signals()
        # a row's (or a surface's) layer gone: the section is built again (an exploration row's: the build errors;
        # Other points and surfaces: a warning), so the preview, the map and an export never show the old one. The
        # rows' boxes move on without a signal of their own (their layer combos allow an empty choice)
        self._schedule()

    # ================================================================ dependent widgets
    def _on_line_layer_changed(self, layer) -> None:
        cur = self.line_feature.currentData()
        # a drawn line stays in use when the layer list changes under it
        self._fill_features(select=cur if (self._applying or cur == DRAWN) else None)
        self._track_layer_signals()
        self._schedule()

    def _on_line_layer_activated(self, *args) -> None:
        """The user chose a line layer: use its first feature."""
        if self.line_feature.currentData() == DRAWN and self.line_layer.currentLayer() is not None:
            self._fill_features(select=None)
        idx = self.line_feature.currentIndex()
        if idx >= 0 and self.line_feature.itemData(idx) != DRAWN:
            self._on_feature_activated(idx)
        self._mark_user()

    def _fill_features(self, select: Any = None) -> None:
        """Feature combo: the drawn line (if any) plus up to 1,000 features of the line layer.

        `select`: DRAWN, a feature id, or None for the first feature (else the drawn line). A feature
        id beyond the first 1,000 is fetched and added; one that no longer exists stays selected as
        "(missing)", so the panel says so instead of quietly using another line.
        """
        combo = self.line_feature
        with self._quiet():
            combo.clear()
            if self._drawn_wkt:
                combo.addItem(QgsApplication.getThemeIcon("/mActionCaptureLine.svg"), self._drawn_desc, DRAWN)
            layer = self.line_layer.currentLayer()
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                names = self._feature_names(layer)
                for text, fid in names:
                    combo.addItem(text, fid)
                if isinstance(select, int) and select not in {fid for _, fid in names}:
                    extra = self._feature_names(layer, fids=[select])
                    combo.addItem(extra[0][0] if extra else f"Feature {select} (missing)", select)
            idx = -1
            if select is not None:
                for i in range(combo.count()):
                    if combo.itemData(i) == select:
                        idx = i
                        break
            if idx < 0 and combo.count():
                first_feature = next((i for i in range(combo.count()) if combo.itemData(i) != DRAWN), None)
                idx = first_feature if (select != DRAWN and first_feature is not None) else 0
            combo.setCurrentIndex(idx)

    @staticmethod
    def _feature_names(layer: QgsVectorLayer, limit: int = 1000,
                       fids: Optional[Sequence[int]] = None) -> List[Tuple[str, int]]:
        """(display name, fid) of the first `limit` features, or of the features `fids` that exist."""
        exp = QgsExpression(layer.displayExpression())
        ctx = QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
        exp.prepare(ctx)
        out = []
        req = QgsFeatureRequest().setFlags(Qgis.FeatureRequestFlag.NoGeometry)
        if fids is not None:
            req.setFilterFids(list(fids))
        else:
            req.setLimit(limit)
        for f in layer.getFeatures(req):
            ctx.setFeature(f)
            v = exp.evaluate(ctx)
            text = str(v) if v not in (None, "") and not exp.hasEvalError() else f"Feature {f.id()}"
            out.append((text, f.id()))
        return out

    def _on_feature_activated(self, index: int) -> None:
        """User chose a feature: a short name such as "B" becomes the end labels B and B'."""
        data = self.line_feature.itemData(index)
        if data not in (None, DRAWN):
            name = self.line_feature.itemText(index).strip()
            if re.fullmatch(r"[A-Za-z0-9]{1,3}", name):
                with self._quiet():
                    self.start_label.setText(name)
                    self.end_label.setText(name + "'")
        self._mark_user()

    def _on_dem_layer_changed(self, layer) -> None:
        with self._quiet():
            self.dem_band.setLayer(layer)
            if layer is not None and self.dem_band.currentBand() < 1:
                self.dem_band.setBand(1)
        self._update_ground_row()
        self._track_layer_signals()
        self._schedule()

    def _update_ground_row(self, *args) -> None:
        self._show_ground_row()
        self._update_problems()

    def _show_ground_row(self) -> None:
        """The ground card's subtitle: the DEM's name, band and cell size (amber "(choose the ground DEM)")."""
        dem = self.dem_layer.currentLayer()
        if dem is None:
            self.ground_sub.setText("(choose the ground DEM)")
            self.ground_sub.setWarn(True)
            return
        band = self.dem_band.currentBand()
        parts = [dem.name(), f"band {band if band >= 1 else 1}"]
        try:
            cell = dem.rasterUnitsPerPixelX()
            factor = _crs_factor_to_ft(dem.crs())
            if cell > 0 and not math.isnan(factor):
                parts.append(f"{fmt_num(round(cell * factor, 2))} ft cells")
        except Exception:
            pass
        self.ground_sub.setText(" · ".join(parts))
        self.ground_sub.setWarn(False)

    # ---- other surfaces
    def _set_surface_rows(self, surfaces: Sequence[dict]) -> None:
        for row in self.surface_rows:
            self._drop_surface_row(row)
        self.surface_rows = []
        for d in surfaces or []:
            self._append_surface_row(d)
        self._renumber_surface_rows()

    def _append_surface_row(self, data: dict, open_editor: bool = False) -> SurfaceRow:
        row = ModelSurfaceRow(data) if (data or {}).get("source") == "mf6" else SurfaceRow(data)
        row.changed.connect(self._on_surfaces_changed)
        row.moveRequested.connect(lambda step, r=row: self.move_surface(r, step))
        row.removeRequested.connect(lambda r=row: self.remove_surface(r))
        row.editorToggled.connect(self._link_surface_cards)        # (0.3.6: a card; its band, its badge)
        row.editorToggled.connect(row.sub_label.setBold)           # (open: its subtitle semibold, as the point rows)
        row.checksChanged.connect(self._update_counts)
        self._surface_layout.addWidget(row)
        self.surface_rows.append(row)
        self.grp_ground.body.watch(row)
        row.set_editor_open(open_editor)
        self._link_surface_cards()
        return row

    def _drop_surface_row(self, row: SurfaceRow) -> None:
        self.grp_ground.body.unwatch(row)
        self._surface_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()

    def _renumber_surface_rows(self) -> None:
        n = len(self.surface_rows)
        for i, row in enumerate(self.surface_rows):
            row.set_position(i, n)
        self._link_surface_cards()

    def _link_surface_cards(self, *args) -> None:
        """Space the Surfaces cards for their bands (widgets.link_cards; the ground row is always the first)."""
        link_cards([self.ground_row] + list(getattr(self, "surface_rows", [])))

    def _on_surfaces_changed(self, *args) -> None:
        self._renumber_surface_rows()
        self._on_widget_changed()

    def _rasters(self) -> List[QgsRasterLayer]:
        """Raster layers in the order of the layers panel (then any others)."""
        prj = QgsProject.instance()
        out: List[QgsRasterLayer] = []
        try:
            for node in prj.layerTreeRoot().findLayers():
                lyr = node.layer()
                if isinstance(lyr, QgsRasterLayer) and lyr not in out:
                    out.append(lyr)
        except Exception:
            pass
        for lyr in prj.mapLayers().values():
            if isinstance(lyr, QgsRasterLayer) and lyr not in out:
                out.append(lyr)
        return out

    def _next_surface_color(self) -> str:
        used = {row.value()["color"].lower() for row in self.surface_rows}
        for c in SURFACE_COLORS:
            if c.lower() not in used:
                return c
        return SURFACE_COLORS[len(self.surface_rows) % len(SURFACE_COLORS)]

    def _default_surface_layer(self) -> Optional[QgsRasterLayer]:
        """The first raster that is neither the DEM nor already a surface, else the DEM's layer."""
        dem = self.dem_layer.currentLayer()
        used = {row.value()["layer_id"] for row in self.surface_rows}
        for lyr in self._rasters():
            if (dem is None or lyr.id() != dem.id()) and lyr.id() not in used:
                return lyr
        return dem

    def add_surface(self, layer: Optional[QgsRasterLayer] = None, band: int = 1, name: str = "",
                    open_editor: bool = True, notify: bool = True) -> SurfaceRow:
        """+ Add surface: a row for `layer` (default: _default_surface_layer), solid, smooth, units auto."""
        if layer is None:
            layer = self._default_surface_layer()
        d = dict(SURFACE_DEFAULTS)
        d.update(layer_id=layer.id() if layer is not None else "", band=int(band), name=name,
                 color=self._next_surface_color())
        row = self._append_surface_row(d, open_editor=open_editor)
        if notify:
            self._on_surfaces_changed()
        return row

    def add_all_bands(self, layer: QgsRasterLayer) -> List[SurfaceRow]:
        """One surface per band of `layer`, named "<layer> band N", colors cycling."""
        rows = [self.add_surface(layer, b, f"{layer.name()} band {b}", open_editor=False, notify=False)
                for b in range(1, layer.bandCount() + 1)]
        self._on_surfaces_changed()
        return rows

    def _last_model(self) -> Tuple[str, str]:
        """(grid file, model CRS) of the last model surface in the list whose grid file exists, else ("", ""):
        where the MODFLOW 6 dialog starts."""
        for row in reversed(self.surface_rows):
            v = row.value() if isinstance(row, ModelSurfaceRow) else {}
            if v.get("mf6_path") and os.path.exists(v["mf6_path"]):
                return v["mf6_path"], v.get("mf6_crs", "")
        return "", ""

    def _last_model_path(self) -> str:
        return self._last_model()[0]

    def add_mf6(self) -> List[SurfaceRow]:
        """+ Add MODFLOW 6…: the dialog, then one row per surface ticked in it (none when cancelled). It starts with
        the last model in the list and its CRS (else the project CRS)."""
        path, crs = self._last_model()
        dlg = MF6Dialog(self, path, crs_from_text(crs))
        try:
            if dlg.exec() != MF6Dialog.DialogCode.Accepted:
                return []
            return self.add_model_surfaces(dlg.surfaces())
        finally:
            dlg.deleteLater()

    def add_model_surfaces(self, surfaces: Sequence[dict]) -> List[SurfaceRow]:
        """Rows for Settings.surfaces dicts of a MODFLOW 6 model (editors closed), saved and rebuilt once."""
        rows = [self._append_surface_row(d, open_editor=False) for d in surfaces]
        if rows:
            self._on_surfaces_changed()
        return rows

    def _fill_bands_menu(self) -> None:
        menu = self._bands_menu
        menu.clear()
        multi = [lyr for lyr in self._rasters() if lyr.bandCount() > 1]
        if not multi:
            act = menu.addAction("No multi-band rasters in the project")
            act.setEnabled(False)
            return
        for lyr in multi:
            act = menu.addAction(QgsApplication.getThemeIcon("/mIconRaster.svg"), f"{lyr.name()} ({lyr.bandCount()} bands)")
            act.triggered.connect(lambda _checked=False, l=lyr: self.add_all_bands(l))

    def move_surface(self, row: SurfaceRow, step: int) -> None:
        if row not in self.surface_rows:
            return
        i = self.surface_rows.index(row)
        j = max(0, min(len(self.surface_rows) - 1, i + int(step)))
        if i == j:
            return
        self.surface_rows.insert(j, self.surface_rows.pop(i))
        self._surface_layout.removeWidget(row)
        self._surface_layout.insertWidget(1 + j, row)          # after the ground row (one card, its editor in it)
        self._on_surfaces_changed()

    def remove_surface(self, row: SurfaceRow) -> None:
        if row not in self.surface_rows:
            return
        self.surface_rows.remove(row)
        self._drop_surface_row(row)
        self._on_surfaces_changed()

    # ---- per-row counts (the rows' "plotted / in the layer", their subtitles and Plotted explorations)
    def _update_type_counts(self, model) -> None:
        """Each row's counts from `model` (None: before a model, or a failed build), silently."""
        infos = list(getattr(model, "point_layers", None) or []) if model is not None else []
        hits = list(model.hits) if model is not None else []
        left = list(getattr(model, "left_off", None) or []) if model is not None else []
        for i, row in enumerate(self.explo_rows):
            if model is None:
                row.set_counts(None)
                row.set_plotted_styles(None)
                continue
            on = (i < len(infos) and infos[i].on) if infos else bool(getattr(model, "has_explorations", True))
            if not on:
                row.set_counts(None)
                row.set_plotted_styles(None)
                continue
            row.set_counts(Counter(h.type_value for h in hits if getattr(h, "layer_index", 0) == i),
                           sum(1 for h in left if getattr(h, "layer_index", 0) == i))
            st = getattr(infos[i], "style", None) if i < len(infos) else None
            # (the style item keys of its plotted explorations: their chips come first in the row's style box)
            row.set_plotted_styles(None if st is None else {
                st.items[h.style_rank].key for h in hits if getattr(h, "layer_index", 0) == i
                and 0 <= getattr(h, "style_rank", -1) < len(st.items)})
        oinfos = list(getattr(model, "other_layers", None) or []) if model is not None else []
        points = list(getattr(model, "other_points", None) or []) if model is not None else []
        areas = list(getattr(model, "other_areas", None) or []) if model is not None else []
        for j, row in enumerate(self.other_rows):
            if model is None or not (j < len(oinfos) and oinfos[j].on):
                row.set_counts(None)
                continue
            if getattr(oinfos[j], "kind", "point") == "polygon":         # (0.3.6: its pieces)
                row.set_counts(Counter(a.type_value for a in areas if a.layer_index == j))
            else:                                                         # its points, or crossings
                row.set_counts(Counter(p.type_value for p in points if p.layer_index == j))

    # ---- the rows' problems (0.3.6, D14: ui.problems)
    def _update_problems(self, *args) -> None:
        """Each card's problems from the last build (self.model; without one, only a row's missing layer): its badge,
        its amber line and its card blocks (with a row's guess, from the row itself). The warnings they show
        (self._mapped) stay out of the status line; the count chips follow; the check card closes when what its
        badge shows changed."""
        if getattr(self, "card_host", None) is None or not hasattr(self, "ground_row"):
            return
        model, host = self.model, self.card_host
        open_badge = host.badge() if host.is_open() else None
        before = list(getattr(open_badge, "blocks", None) or []) if open_badge is not None else None
        # (a model built for other rows, just added, moved or removed: its explorations do not name these rows)
        explo_model = model if self._model_fits(model, "point_layers", self.explo_rows) else None
        other_model = model if self._model_fits(model, "other_layers", self.other_rows) else None
        probs, e_cov = P.explo_problems(explo_model, [self._row_state(r, explo_model) for r in self.explo_rows])
        for row, pr in zip(self.explo_rows, probs):
            row.set_problems(pr)
        prj = QgsProject.instance()
        kinds = [feature_kind(prj.mapLayer(r.stored()["layer_id"]) if r.stored()["layer_id"] else None)
                 for r in self.other_rows]
        probs, o_cov = P.other_problems(other_model, [self._row_state(r) for r in self.other_rows], kinds)
        for row, pr in zip(self.other_rows, probs):
            row.set_problems(pr)
        dem = self.dem_layer.currentLayer()
        dem_name = (getattr(model, "dem_name", "") if model is not None else "") or (dem.name() if dem else "")
        probs, g_cov = P.ground_problems(model, dem_name, lambda st: self._dist(st, self._settings))
        self.ground_row.set_check(probs)
        states = []
        for i, row in enumerate(self.surface_rows, 1):
            v = row.value()
            lyr = row.layer()
            lname = lyr.name() if lyr is not None else ""
            name = row.name_label.text()
            states.append(P.RowState(v, name, False, lname, labels=P.surface_labels(v, i, name, lname)))
        probs, s_cov = P.surface_problems(model, states)
        for row, pr in zip(self.surface_rows, probs):
            row.set_check(pr)
        self._mapped = e_cov | o_cov | g_cov | s_cov
        self._update_counts()
        if open_badge is not None:
            try:
                same = host.is_open() and host.badge() is open_badge and list(open_badge.blocks) == before
            except RuntimeError:
                same = False
            if not same:
                host.close()

    @staticmethod
    def _model_fits(model, attr: str, rows) -> bool:
        """`model` was built for these rows: its infos (`attr`: point_layers, other_layers) name their layers in
        order (a model made by hand without infos fits any rows)."""
        infos = list(getattr(model, attr, None) or []) if model is not None else []
        if not infos:
            return True
        return len(infos) == len(rows) and all(i.layer_id == r.stored()["layer_id"] for i, r in zip(infos, rows))

    def _row_state(self, row, model=None) -> P.RowState:
        """What ui.problems needs of a point row (exploration or Other features): its value, shown name, whether its
        layer is missing, its layer's and table's names, and (with `model`) its table's bad values."""
        v = row.value()
        prj = QgsProject.instance()
        raw = prj.mapLayer(v["layer_id"]) if v.get("layer_id") else None
        lname = raw.name() if isinstance(raw, QgsVectorLayer) and raw.isValid() else ""
        tbl = table_layer(v.get("wl_table_id", "")) if v.get("wl_table_id") else None
        bad = self._table_bad(v, tbl, model) if model is not None and tbl is not None else ()
        return P.RowState(v, row.name_label.text(), row.is_missing(), lname, tbl.name() if tbl is not None else "",
                          (), bad)

    @staticmethod
    def _table_bad(v: dict, tbl: QgsVectorLayer, model) -> Tuple[Tuple[str, str], ...]:
        """Up to CARD_ITEMS + 1 (exploration name, '"text"') of the rows of `tbl` (the water-level table of the row
        `v`) whose level is a text but not a number, when the build warned about its level field (one read of its
        name and level fields, without geometry)."""
        field, name_field = v.get("wl_table_elev_field", ""), v.get("wl_table_name_field", "")
        prefix = f"{tbl.name()}: "
        if not field or not any(w.startswith(prefix) and f" in {field} " in w and "(left out)" in w
                                for w in (model.warnings or [])):
            return ()
        fields = tbl.fields()
        ni, ei = fields.indexOf(name_field), fields.indexOf(field)
        if ei < 0:
            return ()
        req = QgsFeatureRequest().setFlags(Qgis.FeatureRequestFlag.NoGeometry)
        req.setSubsetOfAttributes([i for i in (ni, ei) if i >= 0])
        out: List[Tuple[str, str]] = []
        for f in tbl.getFeatures(req):
            text = not_number_text(f.attribute(ei))
            if not text:
                continue
            name = f.attribute(ni) if ni >= 0 else None
            is_null = getattr(name, "isNull", None)
            name = "" if name is None or (callable(is_null) and is_null()) else str(name)
            out.append((name, f'"{text}"'))
            if len(out) > W.CARD_ITEMS:
                break
        return tuple(out)

    def _on_scale_changed(self, *args) -> None:
        if self._applying:
            return
        if self.grid_auto.isChecked():
            self._show_auto_grid()
        self._on_widget_changed()

    def _show_auto_grid(self) -> None:
        h = self.h_scale.value() or self._settings.h_scale
        v = self.v_scale.value() or self._settings.v_scale
        with self._quiet():
            self.h_major.setValue(h)
            self.h_minor.setValue(h / 10.0)
            self.v_major.setValue(v)
            self.v_minor.setValue(v / 10.0)

    def _on_grid_auto_toggled(self, on: bool) -> None:
        if on and not self._applying:
            self._show_auto_grid()
        self._update_enabled()
        self._sync_grid_ui()
        self._on_widget_changed()

    def _update_enabled(self, *args) -> None:
        manual_grid = not self.grid_auto.isChecked()
        for w in (self.h_major, self.h_minor, self.v_major, self.v_minor):
            w.setEnabled(manual_grid)
        self.grid_spacing_row.setHidden(not manual_grid)      # (0.3.6: shown only while the spacing is typed)
        manual_z = self.z_mode.currentData() == "manual"
        self.z_min.setEnabled(manual_z)
        self.z_max.setEnabled(manual_z)
        self.z_range_row.setHidden(not manual_z)              # (0.3.6: Lowest | Highest only under Manual)
        self.z_auto_row.setHidden(manual_z)                   # (0.3.7: Room below lowest | Fill sheet only under Auto)
        self.z_auto_hint.setWanted(not manual_z)
        self.below_in.setEnabled(not manual_z)
        # a custom page is sized to the drawing (no orientation, no fill); a manual range is drawn as typed
        custom = self.sheet.isCustom()
        self.orientation.setEnabled(not custom)
        for i, tip in enumerate(ORIENT_TIPS):
            self.orientation.setItemToolTip(i, ORIENT_CUSTOM_TIP if custom else tip)
        self.orientation.setToolTip(ORIENT_CUSTOM_TIP if custom else "")
        self.fill_grid.setEnabled(not custom and not manual_z)
        for i, tip in enumerate(FILL_TIPS):
            self.fill_grid.setItemToolTip(i, wrap_tip(FILL_CUSTOM_TIP if custom else tip))
        self.fill_grid.setToolTip(wrap_tip(FILL_CUSTOM_TIP if custom else FILL_TIP))
        line = self.depth_line.isChecked()
        for w in (self.top_mode, self.zero_missing, self.td_label, self.depth_lw_black, self.depth_lw_color,
                  self.btn_lw_reset):
            w.setEnabled(line)
        top_mode = self.top_mode.currentData()
        # the limit checks a table top against LIDAR, and (not with "Table only") a table bottom against top - depth
        # in a row with both a bottom and a depth field
        self.top_max_diff_row.setEnabled(line and (top_mode != "dem" or (
            any(r.has_bottom_and_depth() for r in self.explo_rows) and top_mode != "field")))
        on = self.screens.isChecked()
        self.wl_label.setEnabled(on)
        # the per-row half: each row's boxes follow the shared depth line, top source and screens
        for row in self.explo_rows + self.other_rows:
            row.set_shared(line, top_mode, on)

    # ---- layer signals (edits to the chosen layers, or a new layer CRS, trigger a rebuild).
    # Connections are kept by layer id and only ever disconnected from a layer still in the project: they are
    # dropped when layers are about to be removed (while those still exist) and made again afterwards, so the
    # panel never touches a layer QGIS has deleted (that crashed QGIS now and then).
    def _tracked_ids(self) -> set:
        """The ids of the layers whose edits rebuild the section: the line, the DEM, and every row's layer and
        water-level table (both lists; two rows may share one), missing ones included."""
        ids = {c.currentLayer().id() for c in (self.line_layer, self.dem_layer) if c.currentLayer() is not None}
        return ids | self.explo_list.uses_layer_ids() | self.other_list.uses_layer_ids()

    def _explo_layer_ids(self) -> set:
        """The layers of the exploration rows, whatever their look (so Black -> Color needs no new connection): their
        styleChanged re-reads a Color row's style (0.3.4)."""
        return {r.stored()["layer_id"] for r in self.explo_rows} - {""}

    def _track_layer_signals(self) -> None:
        self._untrack_layer_signals()
        prj = QgsProject.instance()
        line = self.line_layer.currentLayer()
        for layer_id in sorted(self._tracked_ids()):
            layer = prj.mapLayer(layer_id)
            if layer is None:                 # a missing row's layer: nothing to listen to
                continue
            slot = self._on_line_data_changed if line is not None and layer_id == line.id() else self._schedule
            # (an edit in the attribute table or on the map emits layerModified, not dataChanged; rasters have none)
            for name in ("dataChanged", "crsChanged", "layerModified"):
                try:
                    getattr(layer, name).connect(slot)
                    self._layer_conns.append((layer.id(), name, slot))
                except (RuntimeError, TypeError, AttributeError):
                    pass
        # an exploration row's layer: its symbology (a renderer set, a category ticked in the Layers panel, its
        # opacity) emits styleChanged (rendererChanged always comes with it)
        for layer_id in sorted(self._explo_layer_ids()):
            layer = prj.mapLayer(layer_id)
            if layer is None:
                continue
            slot = functools.partial(self._on_point_style_changed, layer_id)
            try:
                layer.styleChanged.connect(slot)
                self._layer_conns.append((layer.id(), "styleChanged", slot))
            except (RuntimeError, TypeError, AttributeError):
                pass

    def _on_point_style_changed(self, layer_id: str, *args) -> None:
        """A layer's style changed in QGIS: every exploration row of it reads the style again; the section is rebuilt
        when one of them is ticked and drawn in Color. Nothing is saved (the settings did not change)."""
        try:
            rows = [r for r in self.explo_rows if r.stored()["layer_id"] == layer_id]
            for r in rows:
                r.refresh_style()
        except RuntimeError:                  # the panel is going away
            return
        if any(v["visible"] and v["look"] == "color" for v in (r.value() for r in rows)):
            self._schedule()

    def _untrack_layer_signals(self) -> None:
        prj = QgsProject.instance()
        for layer_id, name, slot in self._layer_conns:
            layer = prj.mapLayer(layer_id)
            if layer is None:                 # gone: its connections went with it
                continue
            try:
                getattr(layer, name).disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._layer_conns = []

    def _on_line_data_changed(self, *args) -> None:
        self._fill_features(select=self.line_feature.currentData())
        self._schedule()

    # ================================================================ refresh
    def _pipeline(self, s: Settings):
        """core.build -> render.scales.plan. Separate so tests can substitute it."""
        from ..core.build import build_section
        from ..render.scales import plan as make_plan
        model = build_section(s, QgsProject.instance())
        return model, make_plan(model, s)

    def refresh(self) -> None:
        """Rebuild the section now: model, plan, preview, readouts and map feedback."""
        self._timer.stop()
        self._stale = False
        with self._quiet():          # a row shown as missing whose layer is back (repaired with Change Data Source:
            for row in self.explo_rows + self.other_rows:          # the same id, no layer added) shows it again
                if row.name_label.isWarn() and not row.is_missing():
                    row.sync_layer()
        for row in self.surface_rows:                    # model files run again since: their times, units, status
            if isinstance(row, ModelSurfaceRow):
                row.sync()
        s = self.settings()
        self._settings = s
        if self._user_changed:
            self.save_settings()
        self._set_message("")
        try:
            model, plan = self._pipeline(s)
        except SectionError as exc:
            self._fail(str(exc), s)
            return
        except ImportError as exc:
            self._fail(f"XSections is not fully installed ({exc}).", s)
            return
        except Exception as exc:     # a bug: log it, keep the panel usable
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            self._fail(f"Unexpected error: {type(exc).__name__}: {exc} (details in the XSections log).", s)
            return
        self.model, self.plan, self.last_error = model, plan, ""
        self._new_hover_section()
        if plan is not None and s.z_mode != "manual":
            # the (disabled) min / max show the auto limits, so switching to Manual starts from them
            with self._quiet():
                self.z_min.setValue(plan.z_min)
                self.z_max.setValue(plan.z_max)
            s.z_min, s.z_max = self.z_min.value(), self.z_max.value()     # unused in auto mode; kept in step
        if self.preview is not None:
            self.preview.draw(model, s, plan)
        self._update_readouts(model, plan, s)
        self.feedback.show_model(model, s, plan)
        # the rows' problems (0.3.6, ui.problems); what no row shows (and no readout note) goes to the status line
        self._update_problems()
        notes = P.status_warnings(model, plan, self._mapped)
        if plan is not None and not plan.fits:
            self._set_message(plan.message or "The section does not fit the chosen sheet.", ERROR_COLOR)
        elif notes:
            self._set_message(" ".join(notes), WARN_COLOR)
        else:
            self._sync_status()

    def _fail(self, text: str, s: Settings) -> None:
        self.model = self.plan = None
        self.last_error = text
        self._new_hover_section()
        self._set_message(text, ERROR_COLOR)
        if self.preview is not None:
            self.preview.show_message(text)
        for lab in (self.ground_readout, self.explo_readout, self.depth_readout, self.screens_readout,
                    self.other_readout, self.export_readout):
            lab.setWanted(False)
        self._update_type_counts(None)
        self.plotted.set_entries(None)
        self._sync_option_summaries()
        self._update_problems()
        geom, crs = self.current_line_geometry()
        factor = _crs_factor_to_ft(crs) if geom is not None else math.nan
        tol_units = s.tolerance_ft / factor if factor and not math.isnan(factor) else 0.0
        self.feedback.show_line(geom, crs, s.start_label, s.end_label, tol_units)
        self._line_readout_from_geometry(geom, crs, s)
        self._update_chips(s)

    def reload(self) -> None:
        """Refresh button: re-read feature names, and each row's type values and water-level kinds (layers may have
        been edited), rebuild."""
        with self._quiet():
            self._fill_features(select=self.line_feature.currentData())
            for row in self.explo_rows + self.other_rows:
                row.reload_values()
        self.refresh()

    def _set_message(self, text: str, color: str = ERROR_COLOR) -> None:
        """The status line's message: a warning (amber) or an error (red); "" for none (then "Ready · ..." while a
        section is built)."""
        self._message_kind = "warn" if color == WARN_COLOR else "error"
        if color == WARN_COLOR:
            color = self._warn_color()
        elif color == ERROR_COLOR:
            color = self._error_color()
        self.message.setText(text)
        self.message.setStyleSheet(f"QLabel {{ color: {color}; font-weight: 600; }}")
        self.message.setVisible(bool(text))
        self._sync_status()

    def _sync_status(self) -> None:
        """The status line (0.3.6): its dot (error, warn, ok) and, without a message, what the sheet shows (ready_text);
        hidden while there is neither."""
        has_msg = bool(self.message.text())
        ready = not has_msg and self.model is not None
        self.status_text.setText(P.ready_text(self.model) if ready else "")
        self.status_text.setVisible(ready)
        self.status_dot.set_state(self._message_kind if has_msg else ("ok" if ready else ""))
        self.status_bar.setVisible(has_msg or ready)

    # ---- readouts
    def _update_readouts(self, model, plan, s: Settings) -> None:
        warn = self._warn_color()
        start, end = s.start_label or "start", s.end_label or "end"
        az = model.azimuth
        lines = [f"Length <b>{fmt_ft(model.length)}</b> · {len(model.vertex_stations)} vertices · "
                 f"{len(model.bend_stations)} bend{'s' if len(model.bend_stations) != 1 else ''}",
                 f"Direction {_esc(start)} → {_esc(end)}: <b>{compass16(az)}</b> ({fmt_azimuth(az)})"]
        hint = reverse_hint(az, s.start_label, s.end_label)
        if hint:
            lines.append(f"<span style='color:{warn}'>{_esc(hint)}</span>")
        self._show_readout(self.line_readout, lines)

        g = model.ground
        glines = [f"Sampled every {fmt_num(round(g.step, 3))} ft · coverage <b>{g.coverage * 100:.0f}%</b>"]
        if g.gaps:
            spans = [f"{self._dist(a, s)} to {self._dist(b, s)}" for a, b in g.gaps[:3]]
            more = f" and {len(g.gaps) - 3} more" if len(g.gaps) > 3 else ""
            glines.append(f"No DEM data: {', '.join(spans)}{more} (drawn as a gap)")
        if s.dem_z_units == "auto":
            det = self._detected_units()
            if det:        # "unknown" is explained by the core's warning in the message line
                glines.append(f"Elevation units: {det} (from the layer)")
        for sp in getattr(model, "surfaces", None) or []:
            cov = getattr(sp, "coverage", 1.0)
            if cov < 0.995:
                glines.append(f"<span style='color:{warn}'>{_esc(sp.name)}: data along {cov * 100:.0f}% of the "
                              f"line</span>")
        self._show_readout(self.ground_readout, glines)

        self._show_readout(self.explo_readout, self._explo_lines(model, plan, s))
        self._update_type_counts(model)
        self.plotted.set_entries(self._plotted_groups(model, s))
        self._sync_option_summaries()
        dl = depth_sources_line(model.hits, s)
        self._show_readout(self.depth_readout, [dl] if dl else [])
        self._show_readout(self.screens_readout, self._screens_lines(model, s))
        self._show_readout(self.other_readout, self._other_lines(model, s))

        if plan is not None:
            plot_w = plan.plot_length / s.h_scale
            plot_h = (plan.z_max - plan.z_min) / s.v_scale
            xl = [f"VE <b>{fmt_num(round(s.vertical_exaggeration, 3))}×</b> · plot area "
                  f"{plot_w:.2f} × {plot_h:.2f} in",
                  f"Elevation {plan.z_min:,.0f} to {plan.z_max:,.0f} ft"]
            lz = plan.lowest_z
            if lz is not None and not math.isnan(lz) and plan.z_min <= lz <= plan.z_max:
                below = (lz - plan.z_min) / s.v_scale
                what = plan.lowest_what or "the lowest point"
                xl.append(f"{below:.2f} in of grid below {_esc(what)}")
            if plan.pages:
                n = len(plan.pages)
                name = _esc(plan.pages[0].sheet_name)
                xl.append(f"Sheet: <b>{name}</b>" if n == 1 else
                          f"<b>{n} sheets</b>, {name}, with match lines")
            if not plan.fits:
                xl.append(f"<span style='color:{self._error_color()}'><b>Does not fit:</b> {_esc(plan.message)}</span>")
            elif plan.message and len(plan.pages) > 1:        # one sheet: the lines above say it all
                xl.append(f"<span style='color:{self._theme.muted.name()}'>{_esc(plan.message)}</span>")
            for w in getattr(plan, "warnings", None) or []:
                xl.append(f"<span style='color:{warn}'>{_esc(w)}</span>")
            self._show_readout(self.export_readout, xl)
        else:
            self.export_readout.setWanted(False)
        self._update_chips(s)

    def _explo_lines(self, model, plan, s: Settings) -> List[str]:
        """The Explorations readout: what is plotted (per layer when several are on), what he left off, what is near,
        the explorations that run below the frame (amber, inline), past the ends, and up to 6 flags."""
        warn = self._warn_color()
        infos = list(getattr(model, "point_layers", None) or [])
        if not getattr(model, "has_explorations", True):
            return ["No exploration layer is on: ground line and surfaces only." if infos
                    else _esc(NO_POINTS.rstrip("."))]
        on = [i for i in infos if i.on]
        several = len(on) > 1
        k, near = len(getattr(model, "left_off", None) or []), model.near_count
        head = f"Plotted <b>{len(model.hits)}</b>"
        if several:
            head += ": " + ", ".join(f"{i.plotted} {_esc(i.name)}" for i in on)
        if k:
            head += f" · {k} left off by you"
        if near:
            head += f" · {near} more within {fmt_ft(2.5 * s.tolerance_ft)}"
        below = self._below_frame_text(model, plan, s)
        if below:
            head += f" · <span style='color:{warn}'>{below}</span>"
        lines = [head]
        if model.beyond_ends:
            names = ", ".join(_esc(n) for n in model.beyond_ends[:LIST_MAX])
            extra = f" +{len(model.beyond_ends) - LIST_MAX}" if len(model.beyond_ends) > LIST_MAX else ""
            lines.append(f"Past the ends (left out): {len(model.beyond_ends)} ({names}{extra})")
        flagged = [(h.label + (f" ({h.layer_name})" if several and getattr(h, "layer_name", "") else ""), fl)
                   for h in model.hits for fl in (h.flags or [])]
        for label, fl in flagged[:LIST_MAX]:
            lines.append(f"<span style='color:{warn}'>{_esc(label)}: {_esc(fl)}</span>")
        if len(flagged) > LIST_MAX:
            lines.append(f"… and {len(flagged) - LIST_MAX} more flags (see Export points CSV)")
        return lines

    @staticmethod
    def _below_frame_text(model, plan, s: Settings) -> str:
        """"HW-1 runs below the frame (TD 254′)" or "3 run below the frame: HW-1 (TD 254′), …": the explorations of
        rows left out of the elevation range that reach below the frame (rich text, without its colour), with
        "; water level below the frame" (or screen) where the sheet leaves those out; then those of such rows drawn
        without a line down there (no bottom or depth, or Depth line off) whose level or screen lies below the frame:
        "HW-5: water level below the frame" or "2 below the frame: HW-5 (water level), …". "" for none."""
        if plan is None:
            return ""
        z0 = plan.z_min

        def lost(h) -> str:                  # what of h the sheet leaves out below the frame ("" for nothing)
            if not s.screens:
                return ""
            level = any(w.elev < z0 for w in (getattr(h, "water_levels", None) or []))
            top = getattr(h, "screen_top", None)
            screen = top is not None and math.isfinite(top) and top < z0
            return ("screen and water level" if screen and level else "screen" if screen
                    else "water level" if level else "")

        below = [h for h in model.hits if runs_below(h, z0, s)]
        # out-of-range explorations without a line reaching below the frame: their levels and screens there are not
        # drawn either (they never widen the range, decision 22), and nothing else on the sheet says so
        clipped = [h for h in model.hits if not hit_in_range(h) and not runs_below(h, z0, s) and lost(h)]
        parts = []
        if below:
            def detail(h) -> str:
                td = h.total_depth
                text = td_text(td).replace("'", "′") if td is not None and math.isfinite(td) else "no TD"
                return text + (f"; {lost(h)} below the frame" if lost(h) else "")

            if len(below) == 1:
                parts.append(f"{_esc(below[0].label)} runs below the frame ({detail(below[0])})")
            else:
                names = ", ".join(f"{_esc(h.label)} ({detail(h)})" for h in below[:LIST_MAX])
                extra = f" +{len(below) - LIST_MAX}" if len(below) > LIST_MAX else ""
                parts.append(f"{len(below)} run below the frame: {names}{extra}")
        if clipped:
            if len(clipped) == 1:
                parts.append(f"{_esc(clipped[0].label)}: {lost(clipped[0])} below the frame")
            else:
                names = ", ".join(f"{_esc(h.label)} ({lost(h)})" for h in clipped[:LIST_MAX])
                extra = f" +{len(clipped) - LIST_MAX}" if len(clipped) > LIST_MAX else ""
                parts.append(f"{len(clipped)} below the frame: {names}{extra}")
        return "; ".join(parts)

    def _plotted_groups(self, model, s: Settings) -> List[Tuple[str, List[Tuple[str, int, str, str, bool]]]]:
        """Plotted explorations: one group per row that is on with explorations chosen on this section (plotted or
        left off by him), in row order, each sorted by (station, label)."""
        infos = list(getattr(model, "point_layers", None) or [])
        hits, left = list(model.hits), list(getattr(model, "left_off", None) or [])
        chosen_by_row = []
        if not infos:                                      # a model made by hand (tests): one group of its hits
            if not getattr(model, "has_explorations", True) or not hits:
                return []
            lid = self.explo_rows[0].stored()["layer_id"] if self.explo_rows else ""
            chosen_by_row.append((model.points_name or "Explorations", [(h, True) for h in hits], lid))
        for info in infos:
            if not info.on:
                continue
            chosen = ([(h, True) for h in hits if h.layer_index == info.index]
                      + [(h, False) for h in left if h.layer_index == info.index])
            if chosen:
                chosen_by_row.append((info.name, chosen, info.layer_id))
        groups = []
        for title, chosen, lid in chosen_by_row:
            chosen.sort(key=lambda t: (t[0].station, t[0].label))
            groups.append((title, [(getattr(h, "layer_id", "") or lid, int(h.fid), h.label,
                                    self._plotted_detail(h, s), on) for h, on in chosen]))
        return groups

    def _plotted_detail(self, h, s: Settings) -> str:
        """"1,060 ft · 25 ft L · S" (or "10+60 · 25 ft L · S"): where an exploration of the Plotted list is, and the
        direction it was projected in (0.3.7, D3; none for one on the line)."""
        off = f"{h.offset:.1f}".rstrip("0").rstrip(".")
        direction = getattr(h, "direction", "") or ""
        return f"{self._dist(h.station, s)} · {off} ft {h.side}" + (f" · {direction}" if direction else "")

    def _other_lines(self, model, s: Settings) -> List[str]:
        """The Other features readout: per row that is on, what is plotted (points, crossings or pieces), near, past
        the ends and left out for want of an elevation; with up to 6 points, where each one sits; up to 6 of their
        flags (amber; each is also its row's problem line, 0.3.6). Hidden without rows."""
        oinfos = list(getattr(model, "other_layers", None) or [])
        if not oinfos:
            return []
        on = [o for o in oinfos if o.on]
        if not on:
            return ["No point layer is on."]
        warn = self._warn_color()
        points = list(getattr(model, "other_points", None) or [])
        lines, flags = [], []
        for o in on:
            if getattr(o, "kind", "point") == "polygon":                  # its pieces (brackets): no points
                lines.append(f"{_esc(o.name)}: {o.plotted} plotted")
                continue
            pts = [p for p in points if p.layer_index == o.index]
            head = f"{_esc(o.name)}: {len(pts)} plotted"
            if o.near:
                head += f" · {o.near} more within {fmt_ft(2.5 * s.tolerance_ft)}"
            if o.beyond:
                extra = f" +{len(o.beyond) - LIST_MAX}" if len(o.beyond) > LIST_MAX else ""
                head += f" · past the ends: {', '.join(_esc(b) for b in o.beyond[:LIST_MAX])}{extra}"
            if o.no_elevation:
                head += f" · {len(o.no_elevation)} left out (no {_esc(o.elev_field or 'field')})"
            lines.append(head)
            if len(pts) <= LIST_MAX:
                for p in pts:
                    lines.append(f"{_esc(p.label)} {_esc(self._other_where(p, o))}")
            flags += [(p.label, fl) for p in pts for fl in (p.flags or [])]
        for label, fl in flags[:LIST_MAX]:
            lines.append(f"<span style='color:{warn}'>{_esc(label)}: {_esc(fl)}</span>")
        if len(flags) > LIST_MAX:
            lines.append(f"… and {len(flags) - LIST_MAX} more flags")
        return lines

    @staticmethod
    def _other_where(p, o) -> str:
        """Where an other point sits: "on the ground line", "at LIDAR 520.3 ft, 3.0 ft below the ground line", "at
        Elev_ft 523.4 ft, level with the ground line"; "(no Elev_ft) ..." where its field was empty."""
        if p.how == "line":
            where = "on the ground line"
        else:
            d = p.z - p.ground_at_station
            if not math.isfinite(d):
                rel = "no ground line there"
            elif abs(d) < 0.05:
                rel = "level with the ground line"
            elif d < 0:
                rel = f"{-d:.1f} ft below the ground line"
            else:
                rel = f"{d:.1f} ft above the ground line"
            source = "LIDAR" if p.how == "lidar" else o.elev_field
            where = f"at {source} {p.z:.1f} ft, {rel}"
        if p.fell_back and o.elev == "field":
            where = f"(no {o.elev_field or 'field'}) {where}"          # (no field chosen: as the row and the hover)
        return where

    def _screens_wanted(self, s: Settings) -> bool:
        """Screens are on and a ticked row has a screen, water-level or table field."""
        keys = ("screen_top_field", "screen_bottom_field", "wl_field", "atd_field", "wl_table_id")
        return bool(s.screens) and any(r["visible"] and any(r[k] for k in keys) for r in layer_rows(s))

    def _screens_lines(self, model, s: Settings) -> List[str]:
        """"3 screens · 3 measured, 2 ATD water levels", then up to 6 flags about screens or water levels."""
        if not self._screens_wanted(s) or not getattr(model, "has_explorations", True):
            return []
        warn = self._warn_color()
        lines = [_esc(screens_summary(model.hits))]
        flags = [(h.label, fl) for h in model.hits for fl in (h.flags or []) if _SCREEN_FLAG.search(fl)]
        for label, fl in flags[:6]:
            lines.append(f"<span style='color:{warn}'>{_esc(label)}: {_esc(fl)}</span>")
        if len(flags) > 6:
            lines.append(f"… and {len(flags) - 6} more")
        return lines

    def _line_readout_from_geometry(self, geom, crs, s: Settings) -> None:
        """Line facts without a model (e.g. no DEM chosen yet)."""
        factor = _crs_factor_to_ft(crs) if geom is not None else math.nan
        if geom is None or math.isnan(factor):
            self.line_readout.setWanted(False)
            return
        verts = [v for v in geom.vertices()]
        a, b = verts[0], verts[-1]
        az = math.degrees(math.atan2(b.x() - a.x(), b.y() - a.y())) % 360.0
        lines = [f"Length <b>{fmt_ft(geom.length() * factor)}</b> · {len(verts)} vertices",
                 f"Direction {_esc(s.start_label)} → {_esc(s.end_label)}: <b>{compass16(az)}</b> ({fmt_azimuth(az)})"]
        hint = reverse_hint(az, s.start_label, s.end_label)
        if hint:
            lines.append(f"<span style='color:{self._warn_color()}'>{_esc(hint)}</span>")
        self._show_readout(self.line_readout, lines)

    @staticmethod
    def _show_readout(label: Readout, lines: List[str]) -> None:
        """A readout's lines (0.3.6: a Verbose note, shown with Verbose while it has something to say)."""
        label.setText(_html(lines))
        label.setWanted(bool(lines))

    @staticmethod
    def _dist(st: float, s: Settings) -> str:
        return fmt_station(st) if s.distance_labels == "station" else fmt_ft(st)

    def _detected_units(self) -> str:
        dem = self.dem_layer.currentLayer()
        if not isinstance(dem, QgsRasterLayer):
            return ""
        try:
            from ..core.units import detect_z_units
            u = detect_z_units(dem)
        except Exception:
            return ""
        return {"ft": "feet", "ftUS": "US survey feet", "m": "meters"}.get(u, "")

    # ---- header chips
    def chip_texts(self, s: Optional[Settings] = None) -> Dict[str, Tuple[str, bool]]:
        """(text, warn) of each section header's summary chip: "line", "surfaces", "explorations", "other", "scale",
        "style" (0.3.6: Depths and Screens & water are subsections, without chips)."""
        s = s if s is not None else self.settings()
        model, plan = self.model, self.plan
        out: Dict[str, Tuple[str, bool]] = {}

        # line: "A–A′ · 1,534 ft" (the model's length when it is current, else the line's own)
        length = None
        if model is not None and not self._stale:
            has_line = True
            length = model.length
        else:
            geom, crs = self.current_line_geometry()
            has_line = geom is not None
            if has_line:
                factor = _crs_factor_to_ft(crs)
                length = None if math.isnan(factor) else geom.length() * factor
        if not has_line:
            out["line"] = ("Choose a line", True)
        else:
            ends = "–".join(p for p in (pretty_label(s.start_label), pretty_label(s.end_label)) if p)
            parts = [p for p in (ends, fmt_ft(length) if length else "") if p]
            out["line"] = (" · ".join(parts) or "Chosen", False)

        # surfaces: "Ground + 2"
        if self.dem_layer.currentLayer() is None:
            out["surfaces"] = ("Choose a DEM", True)
        else:
            n = sum(1 for d in s.surfaces if d.get("visible", True))
            missing = sum(1 for row in self.surface_rows if row.is_missing())
            text = f"Ground + {n}" if n else "Ground"
            out["surfaces"] = ((f"{text} · {missing} missing", True) if missing else (text, False))

        # explorations and other features: "None", a missing layer (amber), "Off", or what is plotted (other
        # features: points, crossings and pieces)
        out["explorations"] = self._rows_chip(self.explo_rows, lambda: len(model.hits) if model is not None else None)
        other_n = None
        if model is not None and getattr(model, "other_layers", None) is not None:
            other_n = (len(getattr(model, "other_points", None) or [])
                       + len(getattr(model, "other_areas", None) or []))
        out["other"] = self._rows_chip(self.other_rows, lambda: other_n, named=True)

        # scale and sheet: "100′ / 20′ · Letter"
        text = f"{fmt_scale(s.h_scale)}′ / {fmt_scale(s.v_scale)}′"
        if plan is not None and not plan.fits:
            out["scale"] = ("Does not fit", True)
        else:
            if plan is not None and plan.pages:
                text += f" · {sheet_short(plan.pages[0].sheet_name)}"
                if len(plan.pages) > 1:
                    text += f" · {len(plan.pages)} sheets"
            out["scale"] = (text, False)

        # sheet style: "Defaults", else the grid and any depth line widths ("Gray grid · lines 1 / 2.25 pt")
        d = Settings()
        if all(getattr(s, k) == getattr(d, k) for k in STYLE_KEYS):
            out["style"] = ("Defaults", False)
        else:
            text = f"{GRID_NAMES.get(s.grid_color, 'Green')} grid"
            black, color = depth_widths(s)
            if (black, color) != (DEPTH_LW_BLACK, DEPTH_LW_COLOR):
                text += f" · lines {fmt_num(black)} / {fmt_num(color)} pt"
            out["style"] = (text, False)
        return out

    def _rows_chip(self, rows, plotted, named: bool = False) -> Tuple[str, bool]:
        """The chip of a row list: "None" without rows; "Layer missing" (one row) or "2 layers missing" (amber) when
        a ticked row's layer is gone; "Off" when no row is on; one row: "12 plotted" (`named`: "Seeps · 2 plotted";
        "–" before a model); several: "2 of 3 on · 14 plotted". `plotted()`: the model's count (None: no model)."""
        if not rows:
            return "None", False
        values = [r.value() for r in rows]
        missing = sum(1 for r, v in zip(rows, values) if v["visible"] and r.is_missing())
        if missing:
            text = "Layer missing" if len(rows) == 1 else f"{missing} layer{'s' if missing != 1 else ''} missing"
            return text, True
        on = [(r, v) for r, v in zip(rows, values) if v["visible"] and v["layer_id"]]
        if not on:
            return "Off", False
        n = plotted() if self.model is not None else None
        if len(rows) == 1:
            if named:
                lyr = on[0][0].layer()
                name = point_legend_name(on[0][1], lyr.name() if lyr is not None else "")
                return (f"{name} · {n} plotted" if n is not None else name), False
            return (f"{n} plotted" if n is not None else "–"), False
        head = f"{len(on)} of {len(rows)} on"
        return (f"{head} · {n} plotted" if n is not None else head), False

    def _update_chips(self, s: Optional[Settings] = None) -> None:
        if not self.sections:
            return
        chips = self.chip_texts(s)
        for sec, key in zip(self.sections, SECTION_KEYS):
            text, warn = chips[key]
            sec.setChip(text, warn)
        self._update_counts()

    def _update_counts(self, *args) -> None:
        """The amber count chips (0.3.6, D14): the cards of Surfaces, Explorations and Other features with a badge (a
        problem or a guess); none while the section's own chip is amber (it says what is wrong)."""
        if not self.sections:
            return
        for sec, cards in ((self.grp_ground, [self.ground_row] + self.surface_rows), (self.grp_explo, self.explo_rows),
                           (self.grp_other, self.other_rows)):
            try:
                n = 0 if sec.chipWarn() else sum(1 for c in cards if c.has_check())
            except RuntimeError:              # (a row going away)
                continue
            sec.setProblems(n, f"{n} layer{'s' if n != 1 else ''} need{'s' if n == 1 else ''} a look" if n else "")

    # ================================================================ line helpers and actions
    def current_line_geometry(self) -> Tuple[Optional[QgsGeometry], QgsCoordinateReferenceSystem]:
        """The chosen line as it is stored: (geometry, its CRS). (None, invalid CRS) if there is none."""
        data = self.line_feature.currentData()
        if data == DRAWN and self._drawn_wkt:
            g = QgsGeometry.fromWkt(self._drawn_wkt)
            return (g if not g.isEmpty() else None), QgsCoordinateReferenceSystem(self._drawn_crs)
        layer = self.line_layer.currentLayer()
        if isinstance(layer, QgsVectorLayer) and data not in (None, DRAWN):
            f = layer.getFeature(int(data))
            if f.isValid() and f.hasGeometry():
                return QgsGeometry(f.geometry()), layer.crs()
        return None, QgsCoordinateReferenceSystem()

    def set_drawn_line(self, geom: QgsGeometry, crs: QgsCoordinateReferenceSystem, desc: str = "Drawn on map",
                       keep_origin: bool = False) -> None:
        """Use `geom` (in `crs`) as the section line. Stored in a CRS with an authid (EPSG:4326 if needed). A new
        drawing (not `keep_origin`: Reverse keeps it) starts with nothing left off: the "drawn" entries go."""
        if not keep_origin:
            self._reversed_from = None
            self._drop_hidden("drawn")
        g = QgsGeometry(geom)
        if not crs.isValid():
            # a project with "No CRS": keep the coordinates as drawn, with no CRS label (the line is
            # then read in the project CRS, as the canvas showed it); never label them as degrees
            self._drawn_wkt, self._drawn_crs = g.asWkt(4), ""
        else:
            store = crs
            authid = crs.authid()
            portable = bool(authid) and not authid.upper().startswith("USER:")   # USER: ids exist on one machine only
            if not portable or not QgsCoordinateReferenceSystem(authid).isValid():
                store = QgsCoordinateReferenceSystem("EPSG:4326")
            if store != crs:
                g.transform(QgsCoordinateTransform(crs, store, QgsProject.instance()))
            self._drawn_wkt = g.asWkt(10 if store.isGeographic() else 4)
            self._drawn_crs = store.authid()
        self._drawn_desc = desc
        self._fill_features(select=DRAWN)
        self._mark_user()

    def reverse_line(self) -> None:
        """Swap the ends. A layer feature becomes a drawn (reversed) copy; the layer is never edited. Either way the
        new line has exactly the old line's left-off explorations."""
        data = self.line_feature.currentData()
        old_key = line_key(self.settings())
        if data == DRAWN and self._reversed_from is not None:      # reversing twice: back to the feature
            layer_id, fid = self._reversed_from
            layer = QgsProject.instance().mapLayer(layer_id)
            if isinstance(layer, QgsVectorLayer):
                self._reversed_from = None
                self._drawn_wkt = self._drawn_crs = ""
                self._drawn_desc = "Drawn on map"
                with self._quiet():
                    self.line_layer.setLayer(layer)
                    self._fill_features(select=fid)
                self._copy_hidden(old_key, line_key(self.settings()))
                self._mark_user()
                self.refresh()
                return
        geom, crs = self.current_line_geometry()
        curve = _as_curve(geom) if geom is not None else None
        if curve is None:
            self._set_message("Choose or draw a single-part section line first." if geom is None else
                              "This line has several separate parts; draw the section line instead.")
            return
        if data != DRAWN:
            layer = self.line_layer.currentLayer()
            self._reversed_from = (layer.id(), int(data)) if layer is not None else None
            desc = f"{self.line_feature.currentText()} (reversed)"
        else:
            desc = self._drawn_desc
        self.set_drawn_line(QgsGeometry(curve.reversed()), crs, desc=desc, keep_origin=True)
        self._copy_hidden(old_key, line_key(self.settings()))
        self.refresh()

    def use_selected(self) -> None:
        layer = self.line_layer.currentLayer()
        cands = [layer] if isinstance(layer, QgsVectorLayer) else []
        active = self.iface.activeLayer() if hasattr(self.iface, "activeLayer") else None
        if isinstance(active, QgsVectorLayer) and active.geometryType() == Qgis.GeometryType.Line \
                and active not in cands:
            cands.append(active)
        for lyr in cands:
            ids = sorted(lyr.selectedFeatureIds())
            if ids:
                self.select_feature(lyr, ids[0])
                if len(ids) > 1:
                    self._set_message(f"{len(ids)} features are selected in {lyr.name()}; using the first.",
                                      WARN_COLOR)
                return
        self._set_message("Select a line feature first (in the line layer or the active layer).")

    def select_feature(self, layer: QgsVectorLayer, fid: int) -> None:
        """Make `layer` / `fid` the section line (from the pick tool or Use selected)."""
        with self._quiet():
            self.line_layer.setLayer(layer)
            self._fill_features(select=fid)
        idx = self.line_feature.currentIndex()
        if idx >= 0 and self.line_feature.itemData(idx) == fid:
            self._on_feature_activated(idx)
        self._track_layer_signals()
        self._mark_user()

    # ---- map tools
    def _cad(self) -> QgsAdvancedDigitizingDockWidget:
        cad = None
        try:
            cad = self.iface.cadDockWidget()
        except Exception:
            cad = None
        if not isinstance(cad, QgsAdvancedDigitizingDockWidget):
            if self._own_cad is None:
                self._own_cad = QgsAdvancedDigitizingDockWidget(self.canvas)
            cad = self._own_cad
        return cad

    def draw_tool(self) -> DrawSectionTool:
        if self._draw_tool is None:
            self._draw_tool = DrawSectionTool(self.canvas, self._cad())
            self._draw_tool.curveCaptured.connect(self._on_curve_captured)
            self._draw_tool.canceled.connect(self.restore_map_tool)
            self._draw_tool.deactivated.connect(lambda: self._tool_deactivated(self.btn_draw))
        return self._draw_tool

    def pick_tool(self) -> PickLineTool:
        if self._pick_tool is None:
            self._pick_tool = PickLineTool(self.canvas)
            self._pick_tool.featurePicked.connect(self._on_feature_picked)
            self._pick_tool.canceled.connect(self.restore_map_tool)
            self._pick_tool.nothingFound.connect(
                lambda: self._set_message("No line feature there. Click on a line, or press Esc.", WARN_COLOR))
            self._pick_tool.deactivated.connect(lambda: self._tool_deactivated(self.btn_pick))
        return self._pick_tool

    @staticmethod
    def _set_checked(button, on: bool) -> None:
        button.blockSignals(True)
        button.setChecked(on)
        button.blockSignals(False)

    def _tool_deactivated(self, button) -> None:
        """Our tool lost the canvas (Esc, another QGIS tool, or done): uncheck its button and take
        its instructions out of the message line."""
        self._set_checked(button, False)
        self._set_message(self.last_error, ERROR_COLOR)

    def _activate_tool(self, tool) -> None:
        cur = self.canvas.mapTool()
        if cur is not None and cur not in (self._draw_tool, self._pick_tool):
            self._prev_tool = cur
        self.canvas.setMapTool(tool)

    def restore_map_tool(self) -> None:
        """Leave our map tool and go back to the one that was active before."""
        cur = self.canvas.mapTool()
        if cur is None or cur not in (self._draw_tool, self._pick_tool):
            return
        prev = self._prev_tool
        try:
            if prev is not None:
                self.canvas.setMapTool(prev)
                return
        except RuntimeError:      # the previous tool was deleted
            self._prev_tool = None
        self.canvas.unsetMapTool(cur)

    def _on_draw_toggled(self, on: bool) -> None:
        if on:
            self._set_checked(self.btn_pick, False)
            self._activate_tool(self.draw_tool())
            self._set_message("Click the vertices of the section line; right-click to finish, Esc to cancel.",
                              WARN_COLOR)
        else:
            self.restore_map_tool()
            self._set_message(self.last_error, ERROR_COLOR)

    def _on_pick_toggled(self, on: bool) -> None:
        if on:
            self._set_checked(self.btn_draw, False)
            self._activate_tool(self.pick_tool())
            self._set_message("Click a line feature on the map (Esc to cancel).", WARN_COLOR)
        else:
            self.restore_map_tool()
            self._set_message(self.last_error, ERROR_COLOR)

    def _on_curve_captured(self, geom: QgsGeometry) -> None:
        crs = self.canvas.mapSettings().destinationCrs()
        self.restore_map_tool()
        self._set_checked(self.btn_draw, False)
        self._set_message("")
        self.set_drawn_line(geom, crs)
        self.refresh()

    def _on_feature_picked(self, layer, fid) -> None:
        self.restore_map_tool()
        self._set_checked(self.btn_pick, False)
        self._set_message("")
        self.select_feature(layer, int(fid))
        self.refresh()

    # ================================================================ hover: the preview <-> the map
    def _connect_hover(self) -> None:
        """The preview's hover and its Surfaces CSV… button; the map cursor, the map's CRS and the map's Leave (all
        undone in cleanup). The preview may be None, or a stand-in in tests: a signal it lacks is skipped."""
        pv = self.preview
        if pv is not None:
            for name, slot in (("hoverChanged", self._on_preview_hover), ("hoverLeft", self._on_preview_left),
                               ("exportSurfacesRequested", self.export_surfaces_csv)):
                signal = getattr(pv, name, None)
                if signal is None:
                    continue
                try:
                    signal.connect(slot)
                except (AttributeError, TypeError, RuntimeError):
                    continue
                self._preview_conns.append((signal, slot))
        self.canvas.xyCoordinates.connect(self._on_map_xy)
        self.canvas.destinationCrsChanged.connect(self._on_canvas_crs_changed)
        self._map_viewport = self.canvas.viewport()      # (the canvas has no leave signal)
        self._map_viewport.installEventFilter(self)

    def _disconnect_hover(self) -> None:
        self._map_timer.stop()
        self._map_point = None
        for signal, slot in self._preview_conns:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._preview_conns = []
        for signal, slot in ((self.canvas.xyCoordinates, self._on_map_xy),
                             (self.canvas.destinationCrsChanged, self._on_canvas_crs_changed)):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        if self._map_viewport is not None:
            try:
                self._map_viewport.removeEventFilter(self)
            except RuntimeError:
                pass
            self._map_viewport = None

    def eventFilter(self, obj, event) -> bool:
        if obj is self._map_viewport and event.type() == QEvent.Type.Leave:
            self._hide_cursor("map")                     # the mouse left the map
        return super().eventFilter(obj, event)

    def _on_preview_hover(self, station: float, index: int) -> None:
        """The mouse is over the preview at `station` (ft), pointing at hover_target(model, index) (an exploration
        or an other point; -1: none): the marker on the map there, and a ring round that point."""
        from ..core.hover import hover_target          # the explorations, then the other points
        model = self.model
        if model is None or not self._feedback_shown():
            return
        self._cursor_from = "preview"
        self.feedback.show_cursor(station, hit=hover_target(model, index))

    def _on_preview_left(self) -> None:
        """The preview's hover ended: the marker it put on the map goes; when the map's hover cannot go on either
        (the preview's two hover toggles turned off), the marker of the map's own hover too."""
        self._hide_cursor("preview" if self._map_hover_wanted() else "")

    def _feedback_shown(self) -> bool:
        """The section is on the map (MapFeedback.set_visible: not while the panel is closed)."""
        return bool(getattr(self.feedback, "_visible", True))

    def _map_hover_wanted(self) -> bool:
        """The map hover has somewhere to go: a section on the map and in the preview, the preview shown and its
        hover on (its readout row or its popup)."""
        pv = self.preview
        if pv is None or self.model is None or not self._feedback_shown():
            return False
        try:
            return bool(pv.isVisible() and pv.has_section() and pv.hover_enabled())
        except (AttributeError, RuntimeError):
            return False

    def _on_map_xy(self, point) -> None:
        """The mouse moved over the map (canvas CRS): read it at the next turn of the event loop, so that a burst
        of moves makes one update of the preview."""
        if not self._map_hover_wanted():
            self._hide_cursor("map")
            return
        self._map_point = QgsPointXY(point)
        if not self._map_timer.isActive():
            self._map_timer.start()

    def _on_map_hover(self) -> None:
        """The latest map cursor: near the section line (not past its ends), the preview's guide and the map marker
        at its distance; anywhere else, neither."""
        point, self._map_point = self._map_point, None
        if point is None:
            return
        found = self._locate_map_point(point) if self._map_hover_wanted() else None
        if found is None:
            self._hide_cursor("map")
            return
        station, off_ft, side, at = found
        self._cursor_from = "map"
        self.preview.show_guide(station, off_ft, side)
        self.feedback.show_cursor(station, map_point=at)

    def _locate_map_point(self, point: QgsPointXY) -> Optional[Tuple[float, float, str, QgsPointXY]]:
        """(station ft, offset ft, "L"/"R", the point in the section CRS) of a map point (canvas CRS) near the
        section line: within MAP_HOVER_TOLERANCES projection tolerances of it (with explorations or other points on)
        or MAP_HOVER_PX on screen. None past either end of the line, further away, or when the point does not
        transform."""
        model = self.model
        if self._map_line is None:
            self._map_line = self._make_map_line(model)
        if self._map_line is None:
            return None
        locator, ct = self._map_line
        p = QgsPointXY(point)
        if ct is not None:
            try:
                p = ct.transform(p)
            except QgsCsException:
                return None
        found = locator.locate(p)
        if found is None:
            return None
        dist, off, side, foot = found
        f = model.dist_factor or 1.0
        off_ft = off * f
        near_ft = MAP_HOVER_TOLERANCES * self._settings.tolerance_ft \
            if getattr(model, "has_points", getattr(model, "has_explorations", True)) else 0.0
        if off_ft > near_ft:
            px = self._screen_px(point, foot, ct)
            if px is None or px > MAP_HOVER_PX:
                return None
        return min(max(dist * f, 0.0), float(model.length)), off_ft, side, p

    def _screen_px(self, point: QgsPointXY, foot: QgsPointXY, ct) -> Optional[float]:
        """Screen px from a map point (canvas CRS) to a point of the section CRS."""
        if ct is not None:
            try:
                foot = ct.transform(foot, Qgis.TransformDirection.Reverse)
            except QgsCsException:
                return None
        mupp = self.canvas.mapUnitsPerPixel()
        if not mupp or not math.isfinite(mupp):
            return None
        return math.hypot(point.x() - foot.x(), point.y() - foot.y()) / mupp

    def _make_map_line(self, model) -> Optional[Tuple[LineLocator, Optional[QgsCoordinateTransform]]]:
        """The section line, and the canvas -> section CRS transform (None when they are the same CRS)."""
        if model is None or not getattr(model, "line_wkt", ""):
            return None
        line = QgsGeometry.fromWkt(model.line_wkt)
        if line.isEmpty():
            return None
        dest = self.canvas.mapSettings().destinationCrs()
        crs = QgsCoordinateReferenceSystem.fromWkt(model.section_crs_wkt) if model.section_crs_wkt else dest
        ct = None
        if crs.isValid() and dest.isValid() and crs != dest:
            ct = QgsCoordinateTransform(dest, crs, QgsProject.instance())
        return LineLocator(line), ct

    def _on_canvas_crs_changed(self, *args) -> None:
        self._map_line = None                            # (made again for the next map move)

    def _new_hover_section(self) -> None:
        """Another model (or none): the marker and the map's guide go, and the map hover reads the line afresh."""
        self._hide_cursor()
        self._map_line = None

    def _hide_cursor(self, source: str = "") -> None:
        """Take the hover marker off the map and the map's guide off the preview. With `source` ("preview" or
        "map"), only what came from there; "map" also drops a map move still waiting for its turn."""
        if source != "preview":
            self._map_timer.stop()
            self._map_point = None
        if source and self._cursor_from != source:
            return
        if self._cursor_from == "map" and self.preview is not None:
            self.preview.hide_guide()
        self._cursor_from = ""
        self.feedback.hide_cursor()

    # ================================================================ outputs
    def _ensure_model(self) -> bool:
        if self._stale or self._timer.isActive() or self.model is None:
            self.refresh()
        return self.model is not None

    def _bar(self):
        return self.iface.messageBar()

    def _do_export(self, model, s: Settings, plan, path: str, fmt: str, dpi: int) -> List[str]:
        from ..render.export import export
        return export(model, s, plan, path, fmt=fmt, dpi=dpi)

    def _default_dir(self) -> str:
        d = settings_store.user_value("last_export_dir", "")
        if d and os.path.isdir(d):
            return d
        home = QgsProject.instance().homePath()
        return home if home and os.path.isdir(home) else os.path.expanduser("~")

    def export_section(self) -> List[str]:
        """Export… button: file dialog, then render.export.export. Returns the written paths."""
        if not self._ensure_model():
            self._bar().pushWarning("XSections", f"Nothing to export: {self.last_error or 'no section yet.'}")
            return []
        s, model, plan = self._settings, self.model, self.plan
        if not plan.fits:
            self._bar().pushWarning("XSections", f"Not exported: {plan.message or 'the section does not fit the sheet.'}")
            return []
        name = _safe_filename(f"Section {s.start_label}-{s.end_label} H{fmt_num(s.h_scale)} V{fmt_num(s.v_scale)}") \
            + "." + s.export_format
        filters = ";;".join(EXPORT_FILTERS.values())
        path, chosen = QFileDialog.getSaveFileName(self, "Export cross section", os.path.join(self._default_dir(), name),
                                                   filters, EXPORT_FILTERS.get(s.export_format, ""))
        if not path:
            return []
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        if ext not in EXPORT_FILTERS:
            ext = next((k for k, v in EXPORT_FILTERS.items() if v == chosen), s.export_format)
            path = f"{path}.{ext}"
        dpi = s.dpi if ext == "png" else 300
        settings_store.set_user_value("last_export_dir", os.path.dirname(path))
        if ext != s.export_format:          # remember the format the user actually chose
            with self._quiet():
                for i in range(self.fmt.count()):
                    if self.fmt.itemData(i)[0] == ext:
                        self.fmt.setCurrentIndex(i)
                        break
            self._user_changed = True
            self.save_settings()
        try:
            paths = self._do_export(model, s, plan, path, ext, dpi)
        except SectionError as exc:
            self._bar().pushWarning("XSections", f"Not exported: {exc}")
            return []
        except OSError as exc:
            self._write_failed(exc, path, "a PDF viewer or an image editor")
            return []
        except Exception as exc:
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            self._bar().pushCritical("XSections", f"Export failed: {type(exc).__name__}: {exc}")
            return []
        paths = list(paths or [path])
        self._push_paths("Exported", paths)
        return paths

    def _write_failed(self, exc: OSError, path: str, holder: str) -> None:
        """A file could not be written: say why in plain words (a locked file is the usual cause)."""
        QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Warning)
        name = os.path.basename(getattr(exc, "filename", None) or path)
        if isinstance(exc, PermissionError):
            text = (f"Could not write {name}: it is probably open in {holder}. Close it and export again, "
                    "or choose another name.")
        else:
            text = f"Could not write {name}: {exc.strerror or exc}."
        self._bar().pushWarning("XSections", text)

    def _push_paths(self, what: str, paths: List[str]) -> None:
        if len(paths) == 1:
            text = f"{what} {paths[0]}"
        else:
            text = f"{what} {len(paths)} files: " + ", ".join(os.path.basename(p) for p in paths) + \
                   f" in {os.path.dirname(paths[0])}"
        button = QPushButton("Open")
        target = paths[0] if len(paths) == 1 else os.path.dirname(paths[0])
        button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(target)))
        item = QgsMessageBarItem("XSections", text, button, Qgis.MessageLevel.Success, 10)
        self._bar().pushItem(item)

    def save_line_to_layer(self) -> Optional[QgsVectorLayer]:
        """Add the section line to the temporary layer "XSections lines" (created on first use)."""
        if not self._ensure_model():
            self._bar().pushWarning("XSections", f"No section line to save: {self.last_error or 'nothing chosen.'}")
            return None
        s, model = self._settings, self.model
        crs = QgsCoordinateReferenceSystem.fromWkt(model.section_crs_wkt)
        layer = self._lines_layer(crs)
        geom = QgsGeometry.fromWkt(model.line_wkt)
        if layer.crs() != crs:
            geom.transform(QgsCoordinateTransform(crs, layer.crs(), QgsProject.instance()))
        f = QgsFeature(layer.fields())
        f.setGeometry(geom)
        f.setAttributes([s.start_label, s.end_label, float(s.h_scale), float(s.v_scale), float(s.tolerance_ft)])
        ok, added = layer.dataProvider().addFeatures([f])
        layer.updateExtents()
        layer.triggerRepaint()
        if ok and added and self._hidden_of(model.line_key):
            # the saved feature keeps what he left off on this line (a drawn line he saves and comes back to)
            self._copy_hidden(model.line_key, f"{layer.id()}#{added[0].id()}", replace=False)
            self._mark_user()
        self._bar().pushSuccess("XSections", f"Saved {s.start_label}–{s.end_label} to \"{layer.name()}\" "
                                             "(temporary layer: right-click it > Make Permanent to keep it).")
        return layer

    def _lines_layer(self, crs: QgsCoordinateReferenceSystem) -> QgsVectorLayer:
        prj = QgsProject.instance()
        for lyr in prj.mapLayersByName(LINES_LAYER_NAME):
            if isinstance(lyr, QgsVectorLayer) and lyr.providerType() == "memory" \
                    and lyr.customProperty(LINES_LAYER_PROP, False):
                return lyr
        uri = f"LineString?crs={crs.authid()}" if crs.authid() else "LineString"
        layer = QgsVectorLayer(uri, LINES_LAYER_NAME, "memory")
        if not crs.authid():
            layer.setCrs(crs)
        layer.dataProvider().addAttributes([
            QgsField("start", QMetaType.Type.QString), QgsField("end", QMetaType.Type.QString),
            QgsField("h_scale", QMetaType.Type.Double), QgsField("v_scale", QMetaType.Type.Double),
            QgsField("tolerance", QMetaType.Type.Double)])
        layer.updateFields()
        layer.setCustomProperty(LINES_LAYER_PROP, True)
        try:
            pal = QgsPalLayerSettings()
            pal.fieldName = "\"start\" || '–' || \"end\""
            pal.isExpression = True
            pal.placement = Qgis.LabelPlacement.Line
            layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
            layer.setLabelsEnabled(True)
        except Exception:        # labels are a nicety
            pass
        prj.addMapLayer(layer)
        return layer

    def export_points_csv(self) -> str:
        """One row per plotted exploration. Returns the path written ("" if cancelled)."""
        if not self._ensure_model():
            self._bar().pushWarning("XSections", f"No explorations to export: {self.last_error or 'no section yet.'}")
            return ""
        s = self._settings
        name = _safe_filename(f"Section {s.start_label}-{s.end_label} explorations") + ".csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export projected explorations",
                                              os.path.join(self._default_dir(), name), "CSV (*.csv)")
        if not path:
            return ""
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            write_hits_csv(path, self.model, s)
        except OSError as exc:             # usually the previous CSV is still open (Excel locks it)
            self._write_failed(exc, path, "Excel or another program")
            return ""
        settings_store.set_user_value("last_export_dir", os.path.dirname(path))
        self._push_paths(f"Wrote {len(self.model.hits)} explorations to", [path])
        return path

    def export_surfaces_csv(self) -> str:
        """The preview's Surfaces CSV…: the dialog (which lines, one row per point or one column per surface), then
        the file: the ground and the other surfaces as drawn, distance along the section and elevation, feet.
        Returns the path written ("" if cancelled)."""
        if not self._ensure_model():
            self._bar().pushWarning("XSections", f"No surfaces to export: {self.last_error or 'no section yet.'}")
            return ""
        s, model = self._settings, self.model
        pv = self.preview
        parent = pv if isinstance(pv, QWidget) and pv.isVisible() else self      # (the button is on the preview)
        dlg = SurfacesCsvDialog(model, parent)
        try:
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return ""
            opts = dlg.options()
        finally:
            dlg.deleteLater()
        name = _safe_filename(f"Section {s.start_label}-{s.end_label} surfaces") + ".csv"
        path, _ = QFileDialog.getSaveFileName(parent, "Export surfaces to CSV", os.path.join(self._default_dir(), name),
                                              "CSV (*.csv)")
        if not path:
            return ""
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            rows = write_surfaces_csv(path, model, **opts)
        except OSError as exc:             # usually the previous CSV is still open (Excel locks it)
            self._write_failed(exc, path, "Excel or another program")
            return ""
        except Exception as exc:           # a bug: log it, keep the panel usable
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            self._bar().pushCritical("XSections", f"Export failed: {type(exc).__name__}: {exc}")
            return ""
        settings_store.set_user_value("last_export_dir", os.path.dirname(path))
        include = opts.get("include")
        n = len(include) if include is not None else len(hover_lines(model))
        self._push_paths(f"Wrote {n} surface{'s' if n != 1 else ''} ({rows:,} row{'s' if rows != 1 else ''}) to",
                         [path])
        return path

    # ================================================================ teardown
    def cleanup(self) -> None:
        """Everything the dock put on the map or connected (plugin unload)."""
        self._timer.stop()
        self._resync_timer.stop()
        if self._user_changed:
            try:
                self.save_settings()
            except RuntimeError:
                pass
        self.restore_map_tool()
        for tool in (self._draw_tool, self._pick_tool):
            if tool is not None:
                try:
                    if self.canvas.mapTool() is tool:
                        self.canvas.unsetMapTool(tool)
                    tool.deleteLater()
                except RuntimeError:
                    pass
        self._draw_tool = self._pick_tool = None
        self._prev_tool = None
        if self._own_cad is not None:
            self._own_cad.deleteLater()
            self._own_cad = None
        self._untrack_layer_signals()
        prj = QgsProject.instance()
        for signal, slot in ((prj.layersAdded, self._on_layers_added),
                             (prj.layersWillBeRemoved, self._on_layers_will_be_removed),
                             (prj.layersRemoved, self._on_layers_removed),
                             (prj.crsChanged, self._on_project_crs_changed),
                             (prj.writeProject, self._on_write_project)):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        try:
            W.verbose_hub().changed.disconnect(self._on_verbose_changed)
        except (TypeError, RuntimeError):
            pass
        self.card_host.close()
        self.opt_grid.close_popup()                       # (and its application event filter)
        self._hide_cursor()
        self._disconnect_hover()
        self.feedback.remove()


def depth_sources_line(hits, s: Settings) -> str:
    """Where the tops and bottoms came from, e.g. "Tops: 5 ExploElev, 3 LIDAR · Bottoms: 2 BotElev,
    6 top − ExploDepth, 1 none" (rich text). Empty without explorations or without the line.

    Each exploration is named by its own row's fields (core.model.hit_settings): field names in the order first
    seen, then LIDAR, then none (bottoms: the bottom fields, those shifted with the top, top − depth, none); the same
    name in two rows counts once. With one layer this is the text of 0.3.2."""
    if not hits or not s.depth_line:
        return ""
    views: Dict[Tuple[int, str], Settings] = {}
    tops: Dict[Tuple[int, str], int] = {}
    bottoms: Dict[Tuple[int, str], int] = {}
    top_rank = {"field": 0, "dem": 1, "none": 2}
    bottom_rank = {"field": 0, "shifted": 1, "depth": 2, "none": 3}
    for h in hits:
        key = (getattr(h, "layer_index", 0), getattr(h, "layer_id", ""))
        ls = views.get(key)
        if ls is None:
            ls = views[key] = hit_settings(s, h)
        src = h.top_source
        name = {"field": ls.top_field or "table", "dem": "LIDAR"}.get(src, "none")
        k = (top_rank.get(src, 2), name)
        tops[k] = tops.get(k, 0) + 1
        src = getattr(h, "bottom_source", "none")
        name = {"field": ls.bottom_elev_field or "table",
                "shifted": f"{ls.bottom_elev_field or 'table'} shifted with the top",
                "depth": f"top − {ls.depth_field or 'depth'}"}.get(src, "none")
        k = (bottom_rank.get(src, 3), name)
        bottoms[k] = bottoms.get(k, 0) + 1

    def counts(c: Dict[Tuple[int, str], int]) -> str:
        order = sorted(c, key=lambda k: k[0])          # stable: first seen within each kind
        return ", ".join(f"{c[k]} {_esc(k[1])}" for k in order)

    return f"Tops: {counts(tops)} · Bottoms: {counts(bottoms)}"


CSV_COLUMNS = ["name", "type", "station_ft", "station", "offset_ft", "side", "direction", "x", "y",
               "ground_at_station_ft", "ground_at_point_ft", "top_ft", "top_source", "bottom_ft",
               "bottom_source", "depth_ft", "total_depth_ft", "screen_top_ft", "screen_bottom_ft", "water_levels",
               "in_dem_gap", "flags", "layer"]


def _num(v, nd=2):
    if v is None:
        return ""
    try:
        if math.isnan(v):
            return ""
    except TypeError:
        return v
    return round(float(v), nd)


def write_hits_csv(path: str, model, s: Settings) -> None:
    """One row per plotted exploration (model.hits: what he left off is not written; nor are other points), with
    the row's legend name in the last column."""
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_COLUMNS)
        for h in model.hits:
            depth = (h.top - h.bottom) if (h.top is not None and h.bottom is not None) else None
            w.writerow([h.label, h.type_value, _num(h.station), fmt_station(h.station), _num(h.offset), h.side,
                        h.direction, _num(h.x, 3), _num(h.y, 3), _num(h.ground_at_station), _num(h.ground_at_point),
                        _num(h.top), h.top_source, _num(h.bottom), h.bottom_source, _num(depth),
                        _num(h.total_depth), _num(getattr(h, "screen_top", None)),
                        _num(getattr(h, "screen_bottom", None)), _levels_text(getattr(h, "water_levels", None) or []),
                        "yes" if h.in_gap else "", "; ".join(h.flags or []), getattr(h, "layer_name", "")])


def _levels_text(levels) -> str:
    """ "652.8 measured 6/12/2025; 640.1 ATD" (highest first, as the model lists them)."""
    out = []
    for w in levels:
        parts = [f"{w.elev:.2f}".rstrip("0").rstrip("."), "ATD" if w.kind == "atd" else "measured"]
        if w.date:
            parts.append(w.date)
        out.append(" ".join(parts))
    return "; ".join(out)
