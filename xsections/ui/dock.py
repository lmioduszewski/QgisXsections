"""The XSections panel: every setting, live readouts, the debounced rebuild, and the export buttons.

Flow: any change -> 300 ms timer -> refresh(): settings() -> core.build.build_section ->
render.scales.plan -> preview.draw / readouts / header chips / map feedback. A SectionError shows in the
message line at the bottom of the panel, never as a traceback dialog.

Layout (0.2): collapsible sections (Line, Surfaces, Explorations, Depths, Screens & water, Scale & sheet,
Sheet style), all closed whenever the panel opens or a project is loaded; each header carries a summary chip
(amber when something is missing). Small labels sit above their fields, two fields to a row; short choices are
segmented buttons; set-once settings fold under "More: ..." inside their section.

Surfaces: the ground row, then one row per other surface: a raster (widgets.SurfaceRow) or a MODFLOW 6 model surface
(mf6_dialog.ModelSurfaceRow, added with "+ Add MODFLOW 6…", mf6_dialog.MF6Dialog).
"""
from __future__ import annotations

import contextlib
import csv
import math
import os
import re
import traceback
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from qgis.core import (Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsExpression, QgsExpressionContext, QgsExpressionContextUtils, QgsFeature,
                       QgsFeatureRequest, QgsField, QgsFieldProxyModel, QgsGeometry, QgsMessageLog,
                       QgsPalLayerSettings, QgsProject, QgsRasterLayer, QgsUnitTypes,
                       QgsVectorLayer, QgsVectorLayerSimpleLabeling)
from qgis.gui import (QgsAdvancedDigitizingDockWidget, QgsCheckableComboBox, QgsDockWidget, QgsDoubleSpinBox,
                      QgsFieldComboBox, QgsMapLayerComboBox, QgsMessageBarItem, QgsRasterBandComboBox,
                      QgsScrollArea)
from qgis.PyQt.QtCore import QEvent, QLocale, QMetaType, QSize, Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QColor, QDesktopServices, QDoubleValidator, QFont, QPalette
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
                                 QLineEdit, QMenu, QPushButton, QSizePolicy, QToolButton, QTreeWidget,
                                 QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core.model import NO_POINTS, SURFACE_COLORS, SURFACE_DEFAULTS, SectionError, Settings
from . import settings_store
from .map_feedback import MapFeedback
from .maptools import DrawSectionTool, PickLineTool
from .mf6_dialog import MF6Dialog, ModelSurfaceRow, crs_from_text
from .widgets import (CONTROL_H, ClickableArea, CollapsibleSection, Disclosure, ElidedLabel, SegmentedControl,
                      SurfaceRow, Swatch, checkbox_grid, field_box, hrow, link_button, pair, panel_stylesheet,
                      theme_for)

LOG_TAG = "XSections"
DRAWN = "__drawn__"                      # feature-combo data for a line drawn on the map
NO_TYPES = "(no types selected)"         # Settings.types value that matches nothing (empty list = all)
NO_ATD = "(no ATD values)"               # Settings.wl_atd_values value that matches nothing (empty list = automatic)
LINES_LAYER_NAME = "XSections lines"
LINES_LAYER_PROP = "xsections/lines"

# field-name guesses, most specific first: whole names, matched case-insensitively and ignoring _ - and
# spaces (never a part of a name: "botqvr" is not a bottom elevation)
LABEL_NAMES = ["ExploName", "ExploID", "Name", "ID"]
TYPE_NAMES = ["ExploType", "Type"]
TOP_NAMES = ["ExploElev", "TopElev", "Top_Elev", "GroundElev", "GS_Elev", "SurfElev", "Elevation", "Elev"]
BOTTOM_ELEV_NAMES = ["BotElev", "BottomElev", "Bottom_Elev", "BOT_ELEV", "BtmElev", "TD_Elev", "TDElev"]
DEPTH_NAMES = ["ExploDepth", "TotalDepth", "Total_Depth", "TD", "Depth", "Depth_ft", "TD_ft"]
SCREEN_TOP_NAMES = ["ScrTop", "Scr_Top", "ScreenTop", "Screen_Top", "TopScreen", "Scrn_Top", "ScTop", "Scr_Top_ft"]
SCREEN_BOTTOM_NAMES = ["ScrBot", "Scr_Bot", "ScreenBot", "Screen_Bot", "ScreenBottom", "Screen_Bottom", "BotScreen",
                       "Scrn_Bot", "ScBot", "Scr_Bot_ft"]
WL_ELEV_NAMES = ["WL_Elev", "WLElev", "WaterElev", "Water_Elev", "GWElev", "GW_Elev", "SWL_Elev", "WaterLevel", "WL"]
WL_DEPTH_NAMES = ["DepthToGW", "DTW", "Depth_to_GW", "DepthToWater", "GW_Depth"]
WL_NAMES = WL_ELEV_NAMES + WL_DEPTH_NAMES      # elevations first; a guessed depth name sets wl_values to depth
WL_DATE_NAMES = ["WL_Date", "WLDate", "MeasDate", "Meas_Date", "Date_Meas"]
ATD_NAMES = ["ATD_Elev", "ATDElev", "ATD_WL", "WL_ATD", "ATD"]
ATD_DATE_NAMES = ["ATD_Date", "ATDDate", "DrillDate", "Drill_Date", "Date_Drilled"]
TABLE_NAME_NAMES = ["ExploName", "Name", "Boring", "Well", "Location", "ID"]
TABLE_ELEV_NAMES = ["WL_Elev", "WaterElev", "Water_Elev", "Elevation", "Elev"]
TABLE_DATE_NAMES = ["Date", "WL_Date", "MeasDate", "Meas_Date"]
TABLE_KIND_NAMES = ["Kind", "WL_Kind", "WL_Type", "Type", "Status"]

# layer-name hints for a fresh project (no saved settings)
DEM_HINTS = ("lidar", "dem", "dtm", "elev", "terrain")
NOT_DEM_HINTS = ("hillshade", "shade", "ortho", "aerial", "imagery", "image", "photo", "slope", "aspect")
POINT_HINTS = ("explor", "well", "boring", "bore", "cpt", "test", "pit")
# a line layer is only guessed from its name (no fallback): a contour or a road is not a section line
LINE_HINTS = ("section", "xsec", "x-sec", "profile", "transect")

SHEET_CHOICES = [("Smallest that fits", "smallest"), ("Letter 11 × 8.5 in", "letter"),
                 ("Tabloid 17 × 11 in", "tabloid"), ("ANSI C 22 × 17 in", "ansic"), ("ARCH C 24 × 18 in", "archc"),
                 ("ANSI D 34 × 22 in", "ansid"), ("ARCH D 36 × 24 in", "archd"), ("Custom (roll plotter)", "custom")]
SHEET_KEYS = ["letter", "tabloid", "ansic", "archc", "ansid", "archd"]
SHEET_SHORT = {"letter": "Letter", "tabloid": "Tabloid", "ansic": "ANSI C", "archc": "ARCH C", "ansid": "ANSI D",
               "archd": "ARCH D"}
EDGE_CHOICES = [("0.5 in", 0.5), ("0.3 in", 0.3)]
EDGE_TIPS = ["Any printer", "Most laser printers (they print to within 0.25 in; check yours)"]
EDGE_VALUES = [v for _, v in EDGE_CHOICES]
FILL_CHOICES = [("Off", "off"), ("Below", "below"), ("Both", "both")]
FILL_TIPS = ["No extra grid", "Whole major intervals below the section", "Above and below (the larger half below)"]
FORMAT_CHOICES = [("PDF (vector)", ("pdf", 300)), ("PNG, 300 dpi", ("png", 300)), ("PNG, 600 dpi", ("png", 600)),
                  ("SVG", ("svg", 300))]
EXPORT_FILTERS = {"pdf": "PDF (*.pdf)", "png": "PNG image (*.png)", "svg": "SVG drawing (*.svg)"}
SCALE_PRESETS = [1, 2, 5, 10, 20, 30, 40, 50, 60, 100, 200, 300, 400, 500, 600, 1000, 2000, 5000]
COMPASS16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
TOP_MODE_CHIPS = {"field_then_dem": "Table, else LIDAR", "dem": "LIDAR", "field": "Table only"}
STYLE_KEYS = ("grid_color", "data_color", "shade_below", "show_bends", "compact_layout", "edge_margin_in",
              "show_notes", "fill_grid")

ERROR_COLOR = "#c0392b"
WARN_COLOR = "#9a6700"


# ---------------------------------------------------------------- small helpers (also used by tests)
def _norm(name: str) -> str:
    return re.sub(r"[\s_\-]", "", name or "").lower()


def guess_field(field_names: Iterable[str], candidates: Sequence[str]) -> str:
    """First candidate present in `field_names` (case-insensitive, ignoring _ - and spaces), else ""."""
    by_norm = {}
    for name in field_names:
        by_norm.setdefault(_norm(name), name)
    for cand in candidates:
        hit = by_norm.get(_norm(cand))
        if hit:
            return hit
    return ""


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


_SCREEN_FLAG = re.compile(r"screen|water|\bwl\b|\batd\b", re.IGNORECASE)


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


def _combo(items: Sequence[Tuple[str, Any]], parent=None) -> QComboBox:
    c = QComboBox(parent)
    for text, data in items:
        c.addItem(text, data)
    _narrow(c)
    return c


def _segmented(items: Sequence[Tuple[str, Any]], tips: Sequence[str] = ()) -> SegmentedControl:
    seg = SegmentedControl(items)
    for i, tip in enumerate(tips):
        seg.setItemToolTip(i, tip)
    return seg


def _narrow(combo: QComboBox, chars: int = 6) -> None:
    """Let combos shrink with the dock instead of forcing a horizontal scrollbar."""
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(chars)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


def _set_combo_data(combo, value: Any) -> bool:
    for i in range(combo.count()):
        if combo.itemData(i) == value:
            combo.setCurrentIndex(i)
            return True
    return False


def _edge_choice(value: Any) -> float:
    """The printer edge offered nearest to a stored value (0.5 in for anything unreadable)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return EDGE_VALUES[0]
    return min(EDGE_VALUES, key=lambda e: abs(e - v)) if math.isfinite(v) else EDGE_VALUES[0]


def _spin(minimum: float, maximum: float, decimals: int, step: float, suffix: str = "") -> QgsDoubleSpinBox:
    s = QgsDoubleSpinBox()
    s.setRange(minimum, maximum)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setSuffix(suffix)
    s.setShowClearButton(False)
    s.setKeyboardTracking(False)
    s.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    s.setMinimumWidth(48)
    return s


def _field_combo(tooltip: str, numeric: bool = False, allow_empty: bool = True) -> QgsFieldComboBox:
    """A field of a layer (only number fields when `numeric`), or none when `allow_empty`."""
    c = QgsFieldComboBox()
    c.setAllowEmptyFieldName(allow_empty)
    if numeric:
        c.setFilters(QgsFieldProxyModel.Filter.Numeric)
    c.setToolTip(tooltip)
    _narrow(c)
    return c


def _numeric_field_combo(tooltip: str) -> QgsFieldComboBox:
    """A number field of the explorations layer, or none."""
    return _field_combo(tooltip, numeric=True)


def _readout() -> QLabel:
    """The muted line at the bottom of a section (hidden while it has nothing to say)."""
    lab = QLabel("")
    lab.setObjectName("xsReadout")
    lab.setWordWrap(True)
    lab.setTextFormat(Qt.TextFormat.RichText)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    f = QFont(lab.font())
    if f.pointSizeF() > 0:
        f.setPointSizeF(f.pointSizeF() * 0.9)
    lab.setFont(f)
    lab.hide()
    return lab


def _note(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("xsNote")
    lab.setWordWrap(True)
    lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    f = QFont(lab.font())
    if f.pointSizeF() > 0:
        f.setPointSizeF(f.pointSizeF() * 0.9)
    lab.setFont(f)
    return lab


def _html(lines: Iterable[str]) -> str:
    return "<br>".join(line for line in lines if line)


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


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


def _cbox(text: str, tip: str = "", strong: bool = False) -> QCheckBox:
    b = QCheckBox(text)
    b.setToolTip(tip)
    if strong:
        f = QFont(b.font())
        f.setWeight(QFont.Weight.DemiBold)
        b.setFont(f)
    return b


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
        self._layer_conns: List[Tuple[str, str, Any]] = []   # (layer id, signal name, slot)
        self._draw_tool: Optional[DrawSectionTool] = None
        self._pick_tool: Optional[PickLineTool] = None
        self._prev_tool = None
        self._own_cad: Optional[QgsAdvancedDigitizingDockWidget] = None
        self._type_totals: Counter = Counter()
        self._points_none = False         # the user chose no explorations layer (a ground line only)
        self._points_id = ""              # the point layer chosen (by the user, saved or guessed); "" = none
        self._wl_table_id = ""            # the water-level table chosen (saved or by the user); "" = none
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

        self._build_ui()
        self.closedStateChanged.connect(lambda closed: self.feedback.set_visible(not closed))
        with self._quiet():
            self.apply_settings(Settings())
        self._connect_widgets()
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
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.scroll.setWidget(content)

        for build in (self._build_line_group, self._build_ground_group, self._build_explorations_group,
                      self._build_depth_group, self._build_screens_group, self._build_export_group,
                      self._build_style_group):
            lay.addWidget(build())
        self.sections[0].header.first = True
        self.sections[-1].header.last = True
        lay.addStretch(1)
        outer_lay.addWidget(self.scroll, 1)

        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.message.setContentsMargins(4, 0, 4, 0)
        self.message.hide()
        outer_lay.addWidget(self.message)

        # action bar: Refresh, ⋯ (points CSV, save line), Export…
        self.btn_refresh = _tool("/mActionRefresh.svg", "", "Refresh: rebuild the section now (after editing "
                                                            "layers, for example)")
        self.btn_refresh.setFixedSize(32, 28)
        self.btn_more = _tool("", "⋯", "More actions")
        self.btn_more.setFixedSize(32, 28)
        self.btn_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more = QMenu(self.btn_more)
        self.btn_csv = more.addAction(QgsApplication.getThemeIcon("/mActionSaveAs.svg"), "Export points CSV…")
        self.btn_csv.setToolTip("One row per plotted exploration: station, offset, side, top, bottom, flags")
        self.act_save_line = more.addAction(QgsApplication.getThemeIcon("/mActionAddLayer.svg"), "Save line to layer")
        self.act_save_line.setToolTip(f'Add this section line to the temporary layer "{LINES_LAYER_NAME}"')
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
        self.setWidget(outer)
        self.setMinimumWidth(260)
        self._apply_theme()

    def _section(self, title: str, icon: str, name: str) -> CollapsibleSection:
        sec = CollapsibleSection(title, icon, name)
        self.sections.append(sec)
        return sec

    def _more(self, sec: CollapsibleSection, text: str) -> Disclosure:
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
        g.addWidget(pair(field_box("Line layer", self.line_layer), field_box("Feature", self.line_feature)))

        self.btn_pick = _tool("/mActionIdentify.svg", "Pick", "Click a line feature on the map (any visible line "
                                                              "layer)", checkable=True)
        self.btn_draw = _tool("/mActionCaptureLine.svg", "Draw", "Draw on the map: click vertices, right-click to "
                                                                 "finish, Esc to cancel. Snapping works.", checkable=True)
        self.btn_selected = _tool("/mActionSelectRectangle.svg", "Selected", "Use the selected feature of the line "
                                                                             "layer (or of the active layer)")
        g.addWidget(hrow(self.btn_pick, self.btn_draw, self.btn_selected))

        self.start_label = QLineEdit()
        self.end_label = QLineEdit()
        for e, tip in ((self.start_label, "Label of the start (left end) of the section"),
                       (self.end_label, "Label of the end (right end) of the section")):
            e.setFixedWidth(56)
            e.setToolTip(tip)
        self.btn_reverse = _tool("/mActionReverseLine.svg", "", "Reverse: swap the ends, so A is at the other end "
                                                                "(your layer is not edited)")
        if self.btn_reverse.icon().isNull():
            self.btn_reverse.setText("⇄")
        self.btn_reverse.setFixedSize(30, CONTROL_H)
        ends = QWidget()
        el = QHBoxLayout(ends)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(6)
        to = QLabel("to")
        to.setObjectName("xsMuted")
        el.addWidget(self.start_label)
        el.addWidget(to)
        el.addWidget(self.end_label)
        el.addWidget(self.btn_reverse)
        el.addStretch(1)
        self.btn_save_line = link_button("Save line to layer", f'Add this section line to the temporary layer '
                                                               f'"{LINES_LAYER_NAME}"')
        g.addWidget(field_box("End labels", ends, links=[self.btn_save_line]))
        self.line_readout = _readout()
        g.addWidget(self.line_readout)
        self.grp_line = g
        return g

    def _build_ground_group(self) -> QWidget:
        g = self._section("Surfaces", "surfaces", "xsectionsGroundGroup")
        self.surface_list = QFrame()
        self.surface_list.setObjectName("xsSurfaceList")
        self._surface_layout = QVBoxLayout(self.surface_list)
        self._surface_layout.setContentsMargins(1, 1, 1, 1)
        self._surface_layout.setSpacing(0)

        # the ground: always drawn, cannot be removed; its editor holds the DEM layer and band
        ground = QFrame()
        ground.setObjectName("xsGroundRow")
        gl = QHBoxLayout(ground)
        gl.setContentsMargins(6, 4, 6, 4)
        gl.setSpacing(6)
        lock = Swatch(dot=True)
        lock.setToolTip("The ground is always drawn; the explorations sit on it")
        gl.addWidget(lock)
        gl.addWidget(Swatch("#111111"))
        self.ground_name = ClickableArea()
        self.ground_name.setToolTip("Show or hide the ground DEM")
        gn = QVBoxLayout(self.ground_name)
        gn.setContentsMargins(0, 0, 0, 0)
        gn.setSpacing(0)
        self.ground_title = ElidedLabel("Ground")
        self.ground_title.setBold(True)
        self.ground_sub = ElidedLabel("", small=True)
        gn.addWidget(self.ground_title)
        gn.addWidget(self.ground_sub)
        self.ground_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        gl.addWidget(self.ground_name, 1)
        spacer = QWidget()
        spacer.setFixedWidth(24)
        gl.addWidget(spacer)
        self._surface_layout.addWidget(ground)

        self.ground_editor = QFrame()
        self.ground_editor.setObjectName("xsSurfaceEditor")
        ge = QVBoxLayout(self.ground_editor)
        ge.setContentsMargins(28, 7, 8, 9)
        ge.setSpacing(7)
        self.dem_layer = QgsMapLayerComboBox()
        self.dem_layer.setFilters(Qgis.LayerFilter.RasterLayer)
        self.dem_layer.setAllowEmptyLayer(True, "(choose the ground DEM)")
        _narrow(self.dem_layer)
        self.dem_band = QgsRasterBandComboBox()
        _narrow(self.dem_band, 4)
        ge.addWidget(pair(field_box("DEM layer", self.dem_layer), field_box("Band", self.dem_band), (3, 2)))
        self._surface_layout.addWidget(self.ground_editor)
        g.addWidget(self.surface_list)

        self.btn_add_surface = _tool("", "+ Add surface", "Add another raster line: a water table, a model layer…")
        self.btn_add_bands = _tool("", "+ Add all bands…", "One surface per band of a multi-band raster")
        self.btn_add_bands.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._bands_menu = QMenu(self.btn_add_bands)
        self.btn_add_bands.setMenu(self._bands_menu)
        self.btn_add_mf6 = _tool("", "+ Add MODFLOW 6…", "Surfaces read from a MODFLOW 6 model run: the model top, "
                                                         "layer bottoms, heads and the water table")
        add_rows = QWidget()
        al = QVBoxLayout(add_rows)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(5)
        al.addWidget(hrow(self.btn_add_surface, self.btn_add_bands))
        al.addWidget(hrow(self.btn_add_mf6))
        add_rows.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        g.addWidget(add_rows)

        more = self._more(g, "More: units and datum")
        self.z_units = _combo([("Auto (from the layer)", "auto"), ("Feet", "ft"), ("US survey feet", "ftUS"),
                               ("Meters (converted to feet)", "m")])
        self.z_units.setToolTip("Elevation units of the ground DEM")
        self.datum = QLineEdit()
        self.datum.setPlaceholderText("e.g. NAVD88")
        self.datum.setToolTip("Vertical datum, printed in the axis titles and notes")
        more.addWidget(pair(field_box("Ground units", self.z_units), field_box("Vertical datum", self.datum)))
        self.ground_readout = _readout()
        g.addWidget(self.ground_readout)
        self.grp_ground = g
        return g

    def _build_explorations_group(self) -> QWidget:
        g = self._section("Explorations", "explorations", "xsectionsExplorationsGroup")
        self.points_layer = QgsMapLayerComboBox()
        self.points_layer.setFilters(Qgis.LayerFilter.PointLayer)
        self.points_layer.setAllowEmptyLayer(True, "(none: ground line only)")
        _narrow(self.points_layer)
        g.addWidget(field_box("Point layer", self.points_layer))
        self.label_field = QgsFieldComboBox()
        _narrow(self.label_field)
        self.type_field = QgsFieldComboBox()
        self.type_field.setAllowEmptyFieldName(True)
        _narrow(self.type_field)
        g.addWidget(pair(field_box("Label field", self.label_field), field_box("Type field", self.type_field)))

        self.type_list = QTreeWidget()
        self.type_list.setObjectName("xsTypeList")
        self.type_list.setColumnCount(2)
        self.type_list.setHeaderHidden(True)
        self.type_list.setRootIsDecorated(False)
        self.type_list.setUniformRowHeights(True)
        self.type_list.setIndentation(0)
        self.type_list.setFrameShape(QFrame.Shape.NoFrame)
        pal = self.type_list.palette()            # frameless on the panel background (a stylesheet background
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))   # would spoil the check boxes)
        self.type_list.setPalette(pal)
        self.type_list.viewport().setAutoFillBackground(False)
        self.type_list.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.type_list.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.type_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        hdr = self.type_list.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.type_list.setToolTip("Types to plot. Right column: plotted / in the layer.")
        self.btn_types_all = link_button("All", "Plot every type")
        self.btn_types_none = link_button("None", "Plot no type")
        dot = QLabel("·")
        dot.setObjectName("xsMuted")
        g.addWidget(field_box("Types", self.type_list, links=[self.btn_types_all, dot, self.btn_types_none]))

        self.tolerance = _spin(0.0, 1.0e6, 1, 10.0, " ft")
        self.tolerance.setToolTip("Explorations within this distance of the line are projected onto it")
        self.label_dir = _segmented([("Vertical", True), ("Horizontal", False)],
                                    ["Labels written upward", "Horizontal labels, staggered"])
        g.addWidget(pair(field_box("Tolerance", self.tolerance), field_box("Labels", self.label_dir)))
        self.label_text = _combo([("Name only", False), ("Name + offset and direction", True)])
        self.label_text.setToolTip("Name + offset: \"MW-3 · 40 ft N\"")
        g.addWidget(field_box("Label text", self.label_text))
        self.explo_readout = _readout()
        g.addWidget(self.explo_readout)
        self.grp_explo = g
        return g

    def _build_depth_group(self) -> QWidget:
        g = self._section("Depths", "depths", "xsectionsDepthGroup")
        self.depth_line = _cbox("Draw a line from top to bottom",
                                "A line from the top of each exploration down to its bottom", strong=True)
        g.addWidget(self.depth_line)
        self.top_field = _numeric_field_combo("Top (collar or ground) elevation of each exploration, ft. "
                                              "Optional: LIDAR is used where it is empty.")
        self.bottom_elev_field = _numeric_field_combo("Bottom elevation of each exploration, ft. Optional: "
                                                      "where it is empty, the bottom is the top minus the total depth.")
        g.addWidget(pair(field_box("Top elevation", self.top_field),
                         field_box("Bottom elevation", self.bottom_elev_field)))
        self.depth_field = _numeric_field_combo("Total depth below the top, ft. Optional: used where there is "
                                                "no bottom elevation, and for the TD label.")
        self.td_label = _cbox("Label TD 50'", "Write the total depth (TD 50') just below the bottom of each line")
        self.td_label.setMinimumHeight(CONTROL_H)
        g.addWidget(pair(field_box("Total depth", self.depth_field), self.td_label))

        more = self._more(g, "More: where tops come from")
        self.top_mode = _combo([("Table, else LIDAR at the exploration", "field_then_dem"),
                                ("LIDAR at the exploration", "dem"), ("Table only", "field")])
        more.addWidget(field_box("Top from", self.top_mode))
        self.zero_missing = _cbox("Treat 0 as missing", "Shapefiles store an empty number as 0. Applies to the top, "
                                  "bottom and depth fields: untick it if a bottom elevation of 0 ft (sea level) is real")
        more.addWidget(self.zero_missing)
        self.top_max_diff = _spin(0.0, 1.0e5, 1, 5.0, " ft")
        self.top_max_diff.setToolTip("A table top further than this from LIDAR is replaced by LIDAR (flagged). When "
                                     "that happens, a table bottom further than this from LIDAR top − depth is "
                                     "replaced too. 0 turns the checks off.")
        self.top_max_diff.setFixedWidth(76)
        self.top_max_diff.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        before = QLabel("Ignore a table top more than")
        before.setWordWrap(True)
        before.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        after = QLabel("from LIDAR")
        self.top_max_diff_row = QWidget()
        rl = QHBoxLayout(self.top_max_diff_row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(5)
        rl.addWidget(before, 1)
        rl.addWidget(self.top_max_diff, 0)
        rl.addWidget(after, 0)
        more.addWidget(self.top_max_diff_row)
        more.addWidget(_note("Each exploration: top from the table, else LIDAR; bottom from the table, else top − depth."))
        self.depth_readout = _readout()
        g.addWidget(self.depth_readout)
        self.grp_depth = g
        return g

    def _build_screens_group(self) -> QWidget:
        g = self._section("Screens & water", "screens", "xsectionsScreensGroup")
        self.screens = _cbox("Draw screens and water levels", "Well screens, and measured and ATD water levels, "
                             "from fields of the explorations layer or from a table", strong=True)
        g.addWidget(self.screens)
        self.screen_top_field = _numeric_field_combo("Top of the well screen (depth or elevation, see below). "
                                                     "Optional.")
        self.screen_bottom_field = _numeric_field_combo("Bottom of the well screen (depth or elevation, see below). "
                                                        "Optional.")
        g.addWidget(pair(field_box("Screen top", self.screen_top_field),
                         field_box("Screen bottom", self.screen_bottom_field)))
        self.screen_values = _segmented([("Depths", "depth"), ("Elevations", "elevation")],
                                        ["Feet below the top of the exploration", "Elevations, ft"])
        g.addWidget(field_box("Screen values are", self.screen_values))
        self.wl_values = _segmented([("Elevations", "elevation"), ("Depths", "depth")],
                                    ["Water levels are elevations, ft",
                                     "Water levels are depths below the top of the exploration, ft"])
        self.wl_values.setToolTip("Applies to the measured and ATD fields and to the water-level table")
        g.addWidget(field_box("Water levels are", self.wl_values))
        self.wl_field = _numeric_field_combo("Water level (measured): elevation or depth, ft (see above). Drawn as an "
                                             "open triangle joined to the middle of the screen.")
        self.wl_date_field = _field_combo("Date of the measured water level (any field type). Optional.")
        g.addWidget(pair(field_box("Water level (measured)", self.wl_field), field_box("Date", self.wl_date_field),
                         (3, 2)))
        self.atd_field = _numeric_field_combo("Water level at the time of drilling (ATD): elevation or depth, ft (see "
                                              "above). Drawn as a filled triangle on the exploration line.")
        self.atd_date_field = _field_combo("Date of the ATD water level, usually the drilling date (any field type). "
                                           "Optional.")
        g.addWidget(pair(field_box("Water level (ATD)", self.atd_field), field_box("Date", self.atd_date_field),
                         (3, 2)))
        self.wl_label = _segmented([("Off", "off"), ("Elevation", "elev"), ("Elev. + date", "elev_date")],
                                   ["No text", "The elevation beside each water level", "Elevation and date"])
        g.addWidget(field_box("Print beside the symbol", self.wl_label))

        more = self._more(g, "More: water-level table (several per exploration)")
        self.wl_table = QgsMapLayerComboBox()
        self.wl_table.setFilters(Qgis.LayerFilter.VectorLayer)
        self.wl_table.setAllowEmptyLayer(True, "(none)")
        self.wl_table.setToolTip("A table (geometry not needed) with one row per water level")
        _narrow(self.wl_table)
        more.addWidget(field_box("Water-level table", self.wl_table))
        self.wl_table_name_field = _field_combo("Exploration name: matches the explorations' label field (case and "
                                                "spaces ignored)", allow_empty=False)
        self.wl_table_elev_field = _field_combo("Water level: elevation or depth, ft (as set in Water levels are)",
                                                numeric=True, allow_empty=False)
        more.addWidget(pair(field_box("Exploration name", self.wl_table_name_field),
                            field_box("Water level", self.wl_table_elev_field)))
        self.wl_table_date_field = _field_combo("Date of each level (any field type). Optional.")
        self.wl_table_kind_field = _field_combo("Measured or ATD. Optional: without it every row is an ATD level.")
        more.addWidget(pair(field_box("Date", self.wl_table_date_field), field_box("Kind", self.wl_table_kind_field)))
        self.wl_atd_values = QgsCheckableComboBox()
        self.wl_atd_values.setDefaultText("(none)")
        self.wl_atd_values.setToolTip("Kind values drawn as ATD levels (filled triangles); the others are measured")
        _narrow(self.wl_atd_values)
        more.addWidget(field_box("ATD when kind is", self.wl_atd_values))
        self.screens_readout = _readout()
        g.addWidget(self.screens_readout)
        self.grp_screens = g
        return g

    def _build_export_group(self) -> QWidget:
        g = self._section("Scale & sheet", "scale", "xsectionsExportGroup")
        self.h_scale = ScaleCombo()
        self.v_scale = ScaleCombo()
        self.h_scale.setToolTip("Horizontal scale: feet per inch of paper")
        self.v_scale.setToolTip("Vertical scale: feet per inch of paper")
        g.addWidget(pair(field_box("Horizontal", hrow("1 in =", self.h_scale, "ft", spacing=4)),
                         field_box("Vertical", hrow("1 in =", self.v_scale, "ft", spacing=4))))
        self.sheet = _combo(SHEET_CHOICES)
        self.fmt = _combo(FORMAT_CHOICES)
        g.addWidget(pair(field_box("Sheet", self.sheet), field_box("Format", self.fmt)))
        self.z_mode = _segmented([("Auto", "auto"), ("Manual", "manual")],
                                 ["Rounded to the major grid", "Type the range (More)"])
        self.tile = _cbox("Split across sheets", "Tile along the section with match lines and one major interval of "
                          "overlap")
        self.tile.setMinimumHeight(CONTROL_H)
        g.addWidget(pair(field_box("Elevations", self.z_mode), self.tile, (4, 5)))
        self.title_text = QLineEdit()
        self.title_text.setPlaceholderText("Optional title line (project, site…)")
        g.addWidget(field_box("Title", self.title_text))

        more = self._more(g, "More: grid, labels, printers")
        self.grid_auto = _cbox("Grid from scale (1 in, 0.1 in)", "Major grid every paper inch, minor every 0.1 in")
        more.addWidget(self.grid_auto)
        self.h_major = _spin(0.001, 1.0e7, 2, 10.0)
        self.h_minor = _spin(0.001, 1.0e7, 2, 1.0)
        self.v_major = _spin(0.001, 1.0e7, 2, 5.0)
        self.v_minor = _spin(0.001, 1.0e7, 2, 1.0)
        more.addWidget(field_box("Grid H, ft (major / minor)", hrow(self.h_major, "/", self.h_minor, spacing=4)))
        more.addWidget(field_box("Grid V, ft (major / minor)", hrow(self.v_major, "/", self.v_minor, spacing=4)))
        self.z_min = _spin(-1.0e6, 1.0e6, 1, 10.0)
        self.z_max = _spin(-1.0e6, 1.0e6, 1, 10.0)
        more.addWidget(pair(field_box("Min elevation, ft", self.z_min), field_box("Max elevation, ft", self.z_max)))
        self.below_in = _spin(0.0, 20.0, 2, 0.25, " in")
        self.below_in.setToolTip("Grid kept below the lowest point, in paper inches")
        self.distance_labels = _segmented([("Feet", "feet"), ("Stations", "station")],
                                          ["0, 1,000, 2,000", "0+00, 10+00"])
        more.addWidget(pair(field_box("Grid below lowest", self.below_in),
                            field_box("Distances", self.distance_labels)))
        self.allowed_sheets = QgsCheckableComboBox()
        for key in SHEET_KEYS:
            self.allowed_sheets.addItemWithCheckState(SHEET_SHORT[key], Qt.CheckState.Unchecked, key)
        self.allowed_sheets.setToolTip("Sheets your printers take: used by 'Smallest' and for tiling")
        _narrow(self.allowed_sheets)
        more.addWidget(field_box("Printers take", self.allowed_sheets))
        self.export_readout = _readout()
        g.addWidget(self.export_readout)
        self.grp_export = g
        return g

    def _build_style_group(self) -> QWidget:
        g = self._section("Sheet style", "style", "xsectionsStyleGroup")
        defaults = Settings()
        self.grid_color = _segmented([("Green", "green"), ("Gray", "gray")],
                                     ["Green (engineering pad)", "Gray (black-and-white printers)"])
        self.data_color = _segmented([("Black", "black"), ("By type", "type")],
                                     ["Black and gray", "Colored by exploration type"])
        g.addWidget(pair(field_box("Grid", self.grid_color), field_box("Data lines", self.data_color)))
        self.edge_margin = _segmented(EDGE_CHOICES, EDGE_TIPS)
        _set_combo_data(self.edge_margin, _edge_choice(defaults.edge_margin_in))
        self.edge_margin.setToolTip("Clear strip kept at the paper edge, where printers cannot print. Most laser "
                                    "printers print to within 0.25 in; check yours before choosing 0.3 in")
        self.fill_grid = _segmented(FILL_CHOICES, FILL_TIPS)
        _set_combo_data(self.fill_grid, defaults.fill_grid)
        self.fill_grid.setToolTip("Add whole major intervals of grid to use the sheet height (not on a custom page "
                                  "size or with manual elevations). Both puts the larger half below, for the geology")
        g.addWidget(pair(field_box("Printer edge", self.edge_margin), field_box("Fill with grid", self.fill_grid)))
        self.compact_layout = _cbox("Compact layout", "Title on one line, end letters just above the frame, two short "
                                    "note lines beside the scale bar, the elevation title on the left only")
        self.compact_layout.setChecked(defaults.compact_layout)
        self.show_notes = _cbox("Notes", "Scales, grid and data sources under the section. Unticked, the grid, "
                                "graphic scales, axis labels and title stay")
        self.show_notes.setChecked(defaults.show_notes)
        self.show_bends = _cbox("Bend lines", "A dashed vertical line and BEND label at each bend of the section line")
        self.show_bends.setChecked(defaults.show_bends)
        self.shade_below = _cbox("Shade below ground", "Shade below the ground line")
        g.addWidget(checkbox_grid([self.compact_layout, self.show_notes, self.show_bends, self.shade_below]))
        g.addWidget(_note("The defaults leave the most room to draw and the paper clear for colored pencil."))
        self.grp_style = g
        return g

    # ---- theme (light: navy bars; dark: the palette's highlight)
    def _apply_theme(self) -> None:
        t = theme_for(self.palette())
        key = (t.dark, t.bar.name(), t.ink.name(), t.field.name(), t.muted.name())
        if key == self._theme_key:
            return
        self._theme_key = key
        self._theme = t
        w = self.widget()
        if w is not None:
            w.setStyleSheet(panel_stylesheet(t))
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
        """Every section closed, "More" folded, surface editors closed (the ground's open while there is no DEM)."""
        for sec in self.sections:
            sec.setCollapsed(True)
        for d in self._disclosures:
            d.setExpanded(False)
        for row in self.surface_rows:
            row.set_editor_open(False)
        self.ground_editor.setVisible(self.dem_layer.currentLayer() is None)

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
        # surfaces (the ground and the others)
        self.dem_layer.layerChanged.connect(self._on_dem_layer_changed)
        self.dem_layer.activated.connect(self._mark_user)
        self.dem_band.bandChanged.connect(ch)
        self.dem_band.bandChanged.connect(self._update_ground_row)
        self.ground_name.clicked.connect(lambda: self.ground_editor.setVisible(self.ground_editor.isHidden()))
        self.btn_add_surface.clicked.connect(lambda: self.add_surface())
        self._bands_menu.aboutToShow.connect(self._fill_bands_menu)
        self.btn_add_mf6.clicked.connect(lambda: self.add_mf6())
        self.z_units.currentIndexChanged.connect(ch)
        self.datum.textChanged.connect(ch)
        # explorations
        self.points_layer.layerChanged.connect(self._on_points_layer_changed)
        self.points_layer.activated.connect(self._on_points_activated)
        self.label_field.fieldChanged.connect(ch)
        self.type_field.fieldChanged.connect(self._on_type_field_changed)
        self.type_list.itemChanged.connect(lambda _item, _col: ch())
        self.btn_types_all.clicked.connect(lambda: self._check_all_types(True))
        self.btn_types_none.clicked.connect(lambda: self._check_all_types(False))
        self.tolerance.valueChanged.connect(ch)
        self.label_text.currentIndexChanged.connect(ch)
        self.label_dir.currentIndexChanged.connect(ch)
        self.btn_csv.triggered.connect(self.export_points_csv)
        # depths
        self.depth_line.toggled.connect(ch)
        self.depth_line.toggled.connect(self._update_enabled)
        self.top_mode.currentIndexChanged.connect(ch)
        self.top_mode.currentIndexChanged.connect(self._update_enabled)
        for combo in (self.top_field, self.bottom_elev_field, self.depth_field):
            combo.fieldChanged.connect(ch)
        for combo in (self.bottom_elev_field, self.depth_field):
            combo.fieldChanged.connect(self._update_enabled)
        self.zero_missing.toggled.connect(ch)
        self.top_max_diff.valueChanged.connect(ch)
        self.td_label.toggled.connect(ch)
        # screens and water levels
        self.screens.toggled.connect(ch)
        self.screens.toggled.connect(self._update_enabled)
        for combo in (self.screen_top_field, self.screen_bottom_field, self.wl_field, self.wl_date_field,
                      self.atd_field, self.atd_date_field, self.wl_table_name_field, self.wl_table_elev_field,
                      self.wl_table_date_field):
            combo.fieldChanged.connect(ch)
        for combo in (self.wl_field, self.atd_field):
            combo.fieldChanged.connect(self._update_enabled)
        self.screen_values.currentIndexChanged.connect(ch)
        self.wl_values.currentIndexChanged.connect(ch)
        self.wl_label.currentIndexChanged.connect(ch)
        self.wl_table.layerChanged.connect(self._on_wl_table_changed)
        self.wl_table.activated.connect(self._on_wl_table_activated)
        self.wl_table_kind_field.fieldChanged.connect(self._on_wl_kind_changed)
        self.wl_atd_values.checkedItemsChanged.connect(lambda _items: ch())
        # export
        self.h_scale.editTextChanged.connect(self._on_scale_changed)
        self.v_scale.editTextChanged.connect(self._on_scale_changed)
        self.grid_auto.toggled.connect(self._on_grid_auto_toggled)
        for s in (self.h_major, self.h_minor, self.v_major, self.v_minor, self.z_min, self.z_max, self.below_in):
            s.valueChanged.connect(ch)
        self.z_mode.currentIndexChanged.connect(ch)
        self.z_mode.currentIndexChanged.connect(self._update_enabled)
        self.distance_labels.currentIndexChanged.connect(ch)
        self.sheet.currentIndexChanged.connect(ch)
        self.sheet.currentIndexChanged.connect(self._update_enabled)
        self.allowed_sheets.checkedItemsChanged.connect(lambda _items: ch())
        self.tile.toggled.connect(ch)
        self.fmt.currentIndexChanged.connect(ch)
        self.title_text.textChanged.connect(ch)
        # style
        self.grid_color.currentIndexChanged.connect(ch)
        self.data_color.currentIndexChanged.connect(ch)
        self.shade_below.toggled.connect(ch)
        self.show_bends.toggled.connect(ch)
        self.compact_layout.toggled.connect(ch)
        self.edge_margin.currentIndexChanged.connect(ch)
        self.show_notes.toggled.connect(ch)
        self.fill_grid.currentIndexChanged.connect(ch)
        # bottom
        self.btn_refresh.clicked.connect(self.reload)
        self.btn_export.clicked.connect(self.export_section)
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
        if self.isHidden():               # closed or toggled off (not merely behind another dock tab)
            self._was_closed = True

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

        pts = self.points_layer.currentLayer()
        if self._points_gone():
            s.points_layer_id = self._points_id      # build_section says the layer is gone
        else:
            s.points_layer_id = pts.id() if pts is not None else ""
        s.label_field = self.label_field.currentField()
        s.type_field = self.type_field.currentField()
        s.types = self._checked_types() if s.type_field else []
        s.tolerance_ft = self.tolerance.value()
        s.label_offset = bool(self.label_text.currentData())
        s.label_vertical = bool(self.label_dir.currentData())

        s.depth_line = self.depth_line.isChecked()
        s.top_mode = self.top_mode.currentData()
        s.top_field = self.top_field.currentField()
        s.top_max_diff_ft = self.top_max_diff.value()
        s.zero_is_missing = self.zero_missing.isChecked()
        s.bottom_elev_field = self.bottom_elev_field.currentField()
        s.depth_field = self.depth_field.currentField()
        s.td_label = self.td_label.isChecked()

        s.screens = self.screens.isChecked()
        s.screen_top_field = self.screen_top_field.currentField()
        s.screen_bottom_field = self.screen_bottom_field.currentField()
        s.screen_values = self.screen_values.currentData() or "depth"
        s.wl_values = self.wl_values.currentData() or "elevation"
        s.wl_field = self.wl_field.currentField()
        s.wl_date_field = self.wl_date_field.currentField()
        s.atd_field = self.atd_field.currentField()
        s.atd_date_field = self.atd_date_field.currentField()
        table = self.wl_table.currentLayer()
        if table is None and self._wl_table_gone():     # kept as saved, so the panel can say it is missing
            keep = self._settings
            s.wl_table_id = self._wl_table_id
            s.wl_table_name_field, s.wl_table_elev_field = keep.wl_table_name_field, keep.wl_table_elev_field
            s.wl_table_date_field, s.wl_table_kind_field = keep.wl_table_date_field, keep.wl_table_kind_field
            s.wl_atd_values = list(keep.wl_atd_values)
        else:
            s.wl_table_id = table.id() if table is not None else ""
            s.wl_table_name_field = self.wl_table_name_field.currentField()
            s.wl_table_elev_field = self.wl_table_elev_field.currentField()
            s.wl_table_date_field = self.wl_table_date_field.currentField()
            s.wl_table_kind_field = self.wl_table_kind_field.currentField()
            s.wl_atd_values = self._atd_values()
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
        s.sheet = self.sheet.currentData()
        allowed = [k for k in SHEET_KEYS if k in (self.allowed_sheets.checkedItemsData() or [])]
        s.allowed_sheets = allowed or list(Settings().allowed_sheets)
        s.tile = self.tile.isChecked()
        s.export_format, dpi = self.fmt.currentData()
        s.dpi = dpi if s.export_format == "png" else int(self._settings.dpi)
        s.title = self.title_text.text().strip()

        s.grid_color = self.grid_color.currentData()
        s.data_color = self.data_color.currentData()
        s.shade_below = self.shade_below.isChecked()
        s.show_bends = self.show_bends.isChecked()
        s.compact_layout = self.compact_layout.isChecked()
        s.edge_margin_in = float(self.edge_margin.currentData())
        s.show_notes = self.show_notes.isChecked()
        s.fill_grid = self.fill_grid.currentData()
        return s

    def _optional_point_fields(self) -> Tuple[Tuple[QgsFieldComboBox, str, Sequence[str], bool], ...]:
        """(combo, Settings attribute, guesses, numbers only) of the optional fields of the explorations layer."""
        return ((self.top_field, "top_field", TOP_NAMES, True),
                (self.bottom_elev_field, "bottom_elev_field", BOTTOM_ELEV_NAMES, True),
                (self.depth_field, "depth_field", DEPTH_NAMES, True),
                (self.screen_top_field, "screen_top_field", SCREEN_TOP_NAMES, True),
                (self.screen_bottom_field, "screen_bottom_field", SCREEN_BOTTOM_NAMES, True),
                (self.wl_field, "wl_field", WL_NAMES, True),
                (self.wl_date_field, "wl_date_field", WL_DATE_NAMES, False),
                (self.atd_field, "atd_field", ATD_NAMES, True),
                (self.atd_date_field, "atd_date_field", ATD_DATE_NAMES, False))

    def apply_settings(self, s: Settings, guess_fields: bool = False) -> None:
        """Show `s` in the widgets. Layers that no longer exist keep the combo's current choice.

        An optional field left empty stays empty (the user chose none), unless `guess_fields` (fresh
        settings, nothing saved yet): then it is guessed from the field names."""
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

            # explorations (fields before types)
            # (an empty id means none: a ground line only; an id whose layer is gone is kept, so that the
            # panel says so until another layer, or none, is chosen)
            pts = prj.mapLayer(s.points_layer_id) if s.points_layer_id else None
            self.points_layer.setLayer(pts if isinstance(pts, QgsVectorLayer) else None)
            self._points_id = s.points_layer_id
            self._set_field_layers(self.points_layer.currentLayer())
            self._set_field(self.label_field, s.label_field, LABEL_NAMES)
            keep = not guess_fields
            self._set_field(self.type_field, s.type_field, TYPE_NAMES, allow_empty=True, keep_empty=keep)
            if not _set_combo_data(self.wl_values, s.wl_values):
                _set_combo_data(self.wl_values, "elevation")
            for combo, attr, guesses, numeric in self._optional_point_fields():
                guessed = self._set_field(combo, getattr(s, attr), guesses, allow_empty=True, numeric=numeric,
                                          keep_empty=keep)
                if guessed and combo is self.wl_field:
                    self._wl_values_from_guess()
            self._fill_types(s.types)
            self.tolerance.setValue(s.tolerance_ft)
            _set_combo_data(self.label_text, bool(s.label_offset))
            _set_combo_data(self.label_dir, bool(s.label_vertical))

            self.depth_line.setChecked(bool(s.depth_line))
            _set_combo_data(self.top_mode, s.top_mode)
            self.top_max_diff.setValue(s.top_max_diff_ft)
            self.zero_missing.setChecked(bool(s.zero_is_missing))
            self.td_label.setChecked(bool(s.td_label))

            # screens and water levels (the table's fields are guessed only when a table is chosen)
            self.screens.setChecked(bool(s.screens))
            if not _set_combo_data(self.screen_values, s.screen_values):
                _set_combo_data(self.screen_values, "depth")
            if not _set_combo_data(self.wl_label, s.wl_label):
                _set_combo_data(self.wl_label, "off")
            table = prj.mapLayer(s.wl_table_id) if s.wl_table_id else None
            self.wl_table.setLayer(table if isinstance(table, QgsVectorLayer) else None)
            self._wl_table_id = s.wl_table_id
            self._set_table_fields(s.wl_table_name_field, s.wl_table_elev_field, s.wl_table_date_field,
                                   s.wl_table_kind_field, keep_empty=keep)
            self._fill_atd_values(s.wl_atd_values)

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
            self.start_label.setText(s.start_label)
            self.end_label.setText(s.end_label)

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
            _set_combo_data(self.sheet, s.sheet)
            for i in range(self.allowed_sheets.count()):
                on = self.allowed_sheets.itemData(i) in (s.allowed_sheets or [])
                self.allowed_sheets.setItemCheckState(i, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            self.tile.setChecked(bool(s.tile))
            if not _set_combo_data(self.fmt, (s.export_format, int(s.dpi))):
                for i in range(self.fmt.count()):
                    if self.fmt.itemData(i)[0] == s.export_format:
                        self.fmt.setCurrentIndex(i)
                        break
            self.title_text.setText(s.title)

            _set_combo_data(self.grid_color, s.grid_color)
            _set_combo_data(self.data_color, s.data_color)
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
        # saved settings without a point layer: the user chose a ground line only
        self._points_none = s is not None and not s.points_layer_id
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
        self.feedback.clear()
        if self.preview is not None:
            self.preview.show_message("")
        with self._quiet():
            self.apply_settings(Settings())
        self._user_changed = False
        self._stale = True
        self._points_none = False
        self._points_id = ""
        self._wl_table_id = ""
        for lab in (self.line_readout, self.ground_readout, self.explo_readout, self.depth_readout,
                    self.screens_readout, self.export_readout):
            lab.hide()
        self._set_message("")
        self.collapse_all()
        self._update_chips()

    def _guess_layers(self, s: Settings, layers: Optional[Sequence[Any]] = None) -> None:
        """Fill layer ids in a fresh Settings from layer names in the project (or among `layers`)."""
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
        pts = pick(lambda l: isinstance(l, QgsVectorLayer) and l.geometryType() == Qgis.GeometryType.Point,
                   POINT_HINTS, lambda l: True)
        line = pick(lambda l: isinstance(l, QgsVectorLayer) and l.geometryType() == Qgis.GeometryType.Line
                    and not l.customProperty(LINES_LAYER_PROP, False), LINE_HINTS)
        s.dem_layer_id = dem.id() if dem else ""
        s.points_layer_id = pts.id() if pts else ""
        if line is not None:
            s.line_layer_id = line.id()
            first = next(line.getFeatures(QgsFeatureRequest().setLimit(1).setNoAttributes()
                                          .setFlags(Qgis.FeatureRequestFlag.NoGeometry)), None)
            s.line_fid = first.id() if first is not None else None

    def _on_layers_added(self, layers) -> None:
        """Layers added after start-up. A layer box that is still empty gets the same guess as in a
        fresh project (from the new layers only). The point box picks a new layer by itself but reports
        it before the layer is ready (layerChanged(None)), so the field boxes are synced here."""
        if self._applying:
            return
        prj = QgsProject.instance()
        guess = Settings()
        self._guess_layers(guess, layers)
        if self.dem_layer.currentLayer() is None and guess.dem_layer_id:
            self.dem_layer.setLayer(prj.mapLayer(guess.dem_layer_id))
        if self.line_layer.currentLayer() is None and not self._drawn_wkt and guess.line_layer_id:
            self.line_layer.setLayer(prj.mapLayer(guess.line_layer_id))
        if self.label_field.layer() is None and guess.points_layer_id and not self._points_none:
            self.points_layer.setLayer(prj.mapLayer(guess.points_layer_id))    # the point box was empty
        pts, on = self.points_layer.currentLayer(), self.label_field.layer()
        if pts is not None and (not self._points_id or self._points_gone()):
            self._points_id = pts.id()
        if pts is not None and (on is None or on.id() != pts.id()):
            self._on_points_layer_changed(pts)
        for row in self.surface_rows:          # a surface whose raster comes back
            row.sync_layer()
        self._update_chips()

    def _on_layers_will_be_removed(self, *args) -> None:
        self._untrack_layer_signals()          # while the layers still exist (made again in _on_layers_removed)
        self._removing_layers = True
        for row in self.surface_rows:          # the rows' raster boxes move on by themselves: not a choice
            row.set_removing(True)

    def _on_layers_removed(self, *args) -> None:
        self._removing_layers = False
        for row in self.surface_rows:
            row.set_removing(False)
        if self._wl_table_gone():              # the table box moved on to another layer by itself: show none
            with self._quiet():
                self.wl_table.setLayer(None)
                for combo in self._table_combos():
                    combo.setLayer(None)
                self._fill_atd_values([])
            self._update_enabled()
        self._update_ground_row()
        self._update_chips()
        self._track_layer_signals()

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
            self._surface_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self.surface_rows = []
        for d in surfaces or []:
            self._append_surface_row(d)
        self._renumber_surface_rows()

    def _append_surface_row(self, data: dict, open_editor: bool = False) -> SurfaceRow:
        row = ModelSurfaceRow(data) if (data or {}).get("source") == "mf6" else SurfaceRow(data)
        row.changed.connect(self._on_surfaces_changed)
        row.moveRequested.connect(lambda step, r=row: self.move_surface(r, step))
        row.removeRequested.connect(lambda r=row: self.remove_surface(r))
        self._surface_layout.addWidget(row)
        self.surface_rows.append(row)
        row.set_editor_open(open_editor)
        return row

    def _renumber_surface_rows(self) -> None:
        n = len(self.surface_rows)
        for i, row in enumerate(self.surface_rows):
            row.set_position(i, n)

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
        self._surface_layout.insertWidget(2 + j, row)          # after the ground row and its editor
        self._on_surfaces_changed()

    def remove_surface(self, row: SurfaceRow) -> None:
        if row not in self.surface_rows:
            return
        self.surface_rows.remove(row)
        self._surface_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._on_surfaces_changed()

    # ---- explorations fields
    def _field_combos(self) -> Tuple[QgsFieldComboBox, ...]:
        return (self.label_field, self.type_field) + tuple(c for c, _a, _g, _n in self._optional_point_fields())

    def _set_field_layers(self, layer) -> None:
        for combo in self._field_combos():
            combo.setLayer(layer)

    def _set_field(self, combo: QgsFieldComboBox, name: str, guesses: Sequence[str], allow_empty=False,
                   numeric=False, keep_empty=False) -> bool:
        """Keep `name` if the layer has it, else guess from `guesses` (only number fields when `numeric`).
        With `keep_empty` (and `allow_empty`), an empty `name` means none and is kept. True when a field
        was guessed from `guesses`."""
        fields = combo.fields() if combo.layer() is not None else []
        names = [f.name() for f in fields if not numeric or f.isNumeric()]
        if name and name in names:
            combo.setField(name)
            return False
        if not name and allow_empty and keep_empty:
            combo.setField("")
            return False
        guess = guess_field(names, guesses)
        if guess or allow_empty:
            combo.setField(guess)
            return bool(guess)
        if names:
            combo.setField(names[0])
        return False

    def _wl_values_from_guess(self) -> None:
        """A guessed measured water level field sets what the water levels are: a depth name (DepthToGW,
        DTW...) means depths, an elevation name elevations. Never called for a saved field."""
        field = _norm(self.wl_field.currentField())
        if field in {_norm(n) for n in WL_DEPTH_NAMES}:
            _set_combo_data(self.wl_values, "depth")
        elif field in {_norm(n) for n in WL_ELEV_NAMES}:
            _set_combo_data(self.wl_values, "elevation")

    def _on_points_layer_changed(self, *args) -> None:
        if not self._applying:
            layer = self.points_layer.currentLayer()     # the signal's layer can be None while the box fills
            with self._quiet():
                prev = {c: c.currentField() for c in self._field_combos()}
                self._set_field_layers(layer)
                self._set_field(self.label_field, prev[self.label_field], LABEL_NAMES)
                self._set_field(self.type_field, prev[self.type_field], TYPE_NAMES, allow_empty=True)
                for combo, _attr, guesses, numeric in self._optional_point_fields():
                    if self._set_field(combo, prev[combo], guesses, allow_empty=True, numeric=numeric) \
                            and combo is self.wl_field:
                        self._wl_values_from_guess()
                self._fill_types([])
                self._update_enabled()
        self._track_layer_signals()
        self._schedule()

    def _on_points_activated(self, *args) -> None:
        """The user chose a point layer, or none (a ground line only, kept when layers are added later)."""
        layer = self.points_layer.currentLayer()
        self._points_none = layer is None
        self._points_id = layer.id() if layer is not None else ""
        self._mark_user()

    def _points_gone(self) -> bool:
        """The chosen point layer is no longer in the project (removed, or missing from a saved project).
        The panel then shows build_section's error instead of quietly drawing the ground line only."""
        return bool(self._points_id) and not isinstance(QgsProject.instance().mapLayer(self._points_id),
                                                        QgsVectorLayer)

    # ---- water-level table
    def _table_combos(self) -> Tuple[QgsFieldComboBox, ...]:
        return (self.wl_table_name_field, self.wl_table_elev_field, self.wl_table_date_field,
                self.wl_table_kind_field)

    def _set_table_fields(self, name: str, elev: str, date: str, kind: str, keep_empty: bool) -> None:
        layer = self.wl_table.currentLayer()
        for combo in self._table_combos():
            combo.setLayer(layer)
        self._set_field(self.wl_table_name_field, name, TABLE_NAME_NAMES)
        self._set_field(self.wl_table_elev_field, elev, TABLE_ELEV_NAMES, numeric=True)
        self._set_field(self.wl_table_date_field, date, TABLE_DATE_NAMES, allow_empty=True, keep_empty=keep_empty)
        self._set_field(self.wl_table_kind_field, kind, TABLE_KIND_NAMES, allow_empty=True, keep_empty=keep_empty)

    def _on_wl_table_changed(self, *args) -> None:
        if self._removing_layers:              # see _on_layers_removed
            return
        if not self._applying:
            with self._quiet():
                prev = [c.currentField() for c in self._table_combos()]
                self._set_table_fields(*prev, keep_empty=False)
                self._fill_atd_values([])
                self._update_enabled()
        self._track_layer_signals()
        self._schedule()

    def _on_wl_table_activated(self, *args) -> None:
        layer = self.wl_table.currentLayer()
        self._wl_table_id = layer.id() if layer is not None else ""
        self._mark_user()

    def _wl_table_gone(self) -> bool:
        return bool(self._wl_table_id) and not isinstance(QgsProject.instance().mapLayer(self._wl_table_id),
                                                          QgsVectorLayer)

    def _on_wl_kind_changed(self, *args) -> None:
        if self._applying:
            return
        with self._quiet():
            self._fill_atd_values([])
        self._update_enabled()
        self._on_widget_changed()

    def _kind_values(self) -> List[str]:
        table, field = self.wl_table.currentLayer(), self.wl_table_kind_field.currentField()
        if not isinstance(table, QgsVectorLayer) or not field:
            return []
        idx = table.fields().lookupField(field)
        if idx < 0:
            return []
        out = set()
        for v in table.uniqueValues(idx, 500):
            if v is None or (hasattr(v, "isNull") and v.isNull()):
                continue
            text = str(v).strip()
            if text:
                out.add(text)
        return sorted(out, key=str.lower)

    def _fill_atd_values(self, stored: Sequence[str]) -> None:
        """The kind values, checked when drawn as ATD. Nothing stored means the automatic choice: the values
        containing "ATD" (any case), shown checked."""
        combo = self.wl_atd_values
        with self._quiet():
            combo.blockSignals(True)
            try:
                combo.clear()
                stored = [str(v) for v in (stored or [])]
                real = [v for v in stored if v != NO_ATD]
                items = sorted(set(self._kind_values()) | set(real), key=str.lower)
                auto = {v for v in items if "atd" in v.lower()}
                checked = set(stored) if stored else auto
                for v in items:
                    combo.addItemWithCheckState(v, Qt.CheckState.Checked if v in checked else Qt.CheckState.Unchecked, v)
            finally:
                combo.blockSignals(False)

    def _atd_values(self) -> List[str]:
        """Settings.wl_atd_values from the checks: [] when they are the automatic choice."""
        combo = self.wl_atd_values
        items = [(str(combo.itemData(i)), combo.itemCheckState(i) == Qt.CheckState.Checked)
                 for i in range(combo.count())]
        if not items:
            return []
        checked = [v for v, on in items if on]
        auto = [v for v, _on in items if "atd" in v.lower()]
        if set(checked) == set(auto):
            return []
        if not checked:
            return [NO_ATD]
        prev = [v for v in self._settings.wl_atd_values]
        if set(checked) == set(prev):
            return prev
        return checked

    # ---- types
    def _on_type_field_changed(self, *args) -> None:
        if self._applying:
            return
        with self._quiet():
            self._fill_types([])
        self._on_widget_changed()

    def _fill_types(self, types: Sequence[str]) -> None:
        """Checkable list of the type field's values with counts. `types` empty = all checked."""
        try:
            self._fill_types_inner(types)
        finally:
            self._fit_type_list()

    def _fill_types_inner(self, types: Sequence[str]) -> None:
        tl = self.type_list
        with self._quiet():
            tl.clear()
            self._type_totals = Counter()
            layer = self.points_layer.currentLayer()
            field = self.type_field.currentField()
            enabled = isinstance(layer, QgsVectorLayer) and bool(field)
            tl.setEnabled(enabled)
            self.btn_types_all.setEnabled(enabled)
            self.btn_types_none.setEnabled(enabled)
            if not enabled:
                return
            idx = layer.fields().lookupField(field)
            if idx < 0:
                return
            if layer.featureCount() <= 200_000:
                req = (QgsFeatureRequest().setFlags(Qgis.FeatureRequestFlag.NoGeometry)
                       .setSubsetOfAttributes([idx]))
                for f in layer.getFeatures(req):
                    v = f.attribute(idx)
                    if v is not None and str(v) != "":
                        self._type_totals[str(v)] += 1
                values = list(self._type_totals)
            else:
                values = [str(v) for v in layer.uniqueValues(idx) if v is not None and str(v) != ""]
            wanted = set(types or [])
            for v in sorted(values, key=lambda t: t.lower()):
                item = QTreeWidgetItem([v, str(self._type_totals.get(v, ""))])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                on = not wanted or v in wanted
                item.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
                item.setData(0, Qt.ItemDataRole.UserRole, v)
                item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                tl.addTopLevelItem(item)

    def _fit_type_list(self) -> None:
        """Show up to 6 rows without scrolling; never taller than that."""
        tl = self.type_list
        n = tl.topLevelItemCount()
        row = tl.sizeHintForRow(0) if n else tl.fontMetrics().height() + 4
        rows = max(1, min(n, 6))
        tl.setFixedHeight(rows * max(row, 12) + 2 * tl.frameWidth() + 2)

    def _checked_types(self) -> List[str]:
        items = [self.type_list.topLevelItem(i) for i in range(self.type_list.topLevelItemCount())]
        if not items:
            return []
        checked = [it.data(0, Qt.ItemDataRole.UserRole) for it in items if it.checkState(0) == Qt.CheckState.Checked]
        if len(checked) == len(items):
            return []
        return checked or [NO_TYPES]

    def _check_all_types(self, on: bool) -> None:
        with self._quiet():
            for i in range(self.type_list.topLevelItemCount()):
                self.type_list.topLevelItem(i).setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self._on_widget_changed()

    def _update_type_counts(self, model) -> None:
        plotted = Counter(h.type_value for h in model.hits) if model is not None else Counter()
        with self._quiet():
            for i in range(self.type_list.topLevelItemCount()):
                it = self.type_list.topLevelItem(i)
                v = it.data(0, Qt.ItemDataRole.UserRole)
                total = self._type_totals.get(v, "")
                it.setText(1, f"{plotted.get(v, 0)} / {total}" if model is not None else str(total))

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
        self._on_widget_changed()

    def _update_enabled(self, *args) -> None:
        manual_grid = not self.grid_auto.isChecked()
        for w in (self.h_major, self.h_minor, self.v_major, self.v_minor):
            w.setEnabled(manual_grid)
        manual_z = self.z_mode.currentData() == "manual"
        self.z_min.setEnabled(manual_z)
        self.z_max.setEnabled(manual_z)
        self.below_in.setEnabled(not manual_z)
        self.allowed_sheets.setEnabled(self.sheet.currentData() == "smallest")
        # a custom page is sized to the drawing; a manual range is drawn as typed
        self.fill_grid.setEnabled(self.sheet.currentData() != "custom" and not manual_z)
        line = self.depth_line.isChecked()
        for w in (self.top_mode, self.bottom_elev_field, self.depth_field, self.zero_missing, self.td_label):
            w.setEnabled(line)
        table_top = line and self.top_mode.currentData() != "dem"
        self.top_field.setEnabled(table_top)
        # the same limit checks a table bottom against top - depth (not with "Table only")
        bottom_check = (line and self.top_mode.currentData() != "field"
                        and bool(self.bottom_elev_field.currentField()) and bool(self.depth_field.currentField()))
        self.top_max_diff_row.setEnabled(table_top or bottom_check)
        # screens and water levels: off with the box; a date only with its level; table fields only with a table
        on = self.screens.isChecked()
        for w in (self.screen_top_field, self.screen_bottom_field, self.screen_values, self.wl_values, self.wl_field,
                  self.atd_field, self.wl_label, self.wl_table):
            w.setEnabled(on)
        self.wl_date_field.setEnabled(on and bool(self.wl_field.currentField()))
        self.atd_date_field.setEnabled(on and bool(self.atd_field.currentField()))
        table = on and self.wl_table.currentLayer() is not None
        for w in self._table_combos():
            w.setEnabled(table)
        self.wl_atd_values.setEnabled(table and bool(self.wl_table_kind_field.currentField()))

    # ---- layer signals (edits to the chosen layers, or a new layer CRS, trigger a rebuild).
    # Connections are kept by layer id and only ever disconnected from a layer still in the project: they are
    # dropped when layers are about to be removed (while those still exist) and made again afterwards, so the
    # panel never touches a layer QGIS has deleted (that crashed QGIS now and then).
    def _track_layer_signals(self) -> None:
        self._untrack_layer_signals()
        for combo in (self.line_layer, self.points_layer, self.dem_layer, self.wl_table):
            layer = combo.currentLayer()
            if layer is None:
                continue
            slot = self._on_line_data_changed if combo is self.line_layer else self._schedule
            for name in ("dataChanged", "crsChanged"):
                try:
                    getattr(layer, name).connect(slot)
                    self._layer_conns.append((layer.id(), name, slot))
                except (RuntimeError, TypeError):
                    pass

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
        if self._points_gone() and self.points_layer.currentLayer() is not None:
            with self._quiet():                          # the box moved on by itself when the layer went
                self.points_layer.setLayer(None)
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
        covered = {f"{h.label}: {fl}" for h in model.hits for fl in (h.flags or [])} | {NO_POINTS}
        notes = [w for w in (model.warnings or []) if w not in covered
                 and not w.startswith(("Left out past the ends", "No DEM data along"))]   # already in readouts
        notes = list(getattr(plan, "warnings", None) or []) + notes
        if plan is not None and not plan.fits:
            self._set_message(plan.message or "The section does not fit the chosen sheet.", ERROR_COLOR)
        elif notes:
            self._set_message(" ".join(notes), WARN_COLOR)

    def _fail(self, text: str, s: Settings) -> None:
        self.model = self.plan = None
        self.last_error = text
        self._set_message(text, ERROR_COLOR)
        if self.preview is not None:
            self.preview.show_message(text)
        for lab in (self.ground_readout, self.explo_readout, self.depth_readout, self.screens_readout,
                    self.export_readout):
            lab.hide()
        self._update_type_counts(None)
        geom, crs = self.current_line_geometry()
        factor = _crs_factor_to_ft(crs) if geom is not None else math.nan
        tol_units = s.tolerance_ft / factor if factor and not math.isnan(factor) else 0.0
        self.feedback.show_line(geom, crs, s.start_label, s.end_label, tol_units)
        self._line_readout_from_geometry(geom, crs, s)
        self._update_chips(s)

    def reload(self) -> None:
        """Refresh button: re-read feature names and type values (layers may have been edited), rebuild."""
        with self._quiet():
            self._fill_features(select=self.line_feature.currentData())
            self._fill_types(self._checked_types())
            if self.wl_table.currentLayer() is not None:
                self._fill_atd_values(self._atd_values())
        self.refresh()

    def _set_message(self, text: str, color: str = ERROR_COLOR) -> None:
        if color == WARN_COLOR:
            color = self._warn_color()
        elif color == ERROR_COLOR:
            color = self._error_color()
        self.message.setText(text)
        self.message.setStyleSheet(f"QLabel {{ color: {color}; font-weight: 600; }}")
        self.message.setVisible(bool(text))

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

        near = model.near_count
        if not getattr(model, "has_explorations", True):
            elines = [_esc(NO_POINTS.rstrip("."))]
        else:
            elines = [f"Plotted <b>{len(model.hits)}</b>"
                      + (f" · {near} more within {fmt_ft(2.5 * s.tolerance_ft)}" if near else "")]
        if model.beyond_ends:
            names = ", ".join(_esc(n) for n in model.beyond_ends[:6])
            extra = f" +{len(model.beyond_ends) - 6}" if len(model.beyond_ends) > 6 else ""
            elines.append(f"Past the ends (left out): {len(model.beyond_ends)} ({names}{extra})")
        flagged = [(h.label, fl) for h in model.hits for fl in (h.flags or [])]
        for label, fl in flagged[:6]:
            elines.append(f"<span style='color:{warn}'>{_esc(label)}: {_esc(fl)}</span>")
        if len(flagged) > 6:
            elines.append(f"… and {len(flagged) - 6} more flags (see Export points CSV)")
        self._show_readout(self.explo_readout, elines)
        self._update_type_counts(model)
        dl = depth_sources_line(model.hits, s)
        self._show_readout(self.depth_readout, [dl] if dl else [])
        self._show_readout(self.screens_readout, self._screens_lines(model, s))

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
            self.export_readout.hide()
        self._update_chips(s)

    def _screens_wanted(self, s: Settings) -> bool:
        return s.screens and bool(s.screen_top_field or s.screen_bottom_field or s.wl_field or s.atd_field
                                  or s.wl_table_id)

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
            self.line_readout.hide()
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
    def _show_readout(label: QLabel, lines: List[str]) -> None:
        label.setText(_html(lines))
        label.setVisible(bool(lines))

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
        """(text, warn) of each section header's summary chip, by section object name suffix."""
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

        # explorations
        if self._points_gone():
            out["explorations"] = ("Layer missing", True)
        elif self.points_layer.currentLayer() is None:
            out["explorations"] = ("None", False)
        elif model is not None and getattr(model, "has_explorations", True):
            out["explorations"] = (f"{len(model.hits)} plotted", False)
        else:
            out["explorations"] = ("–", False)

        # depths
        out["depths"] = (TOP_MODE_CHIPS.get(s.top_mode, "–") if s.depth_line else "Off", False)

        # screens and water levels
        if not s.screens:
            out["screens"] = ("Off", False)
        elif not self._screens_wanted(s) or model is None:
            out["screens"] = ("–", False)
        else:
            n, measured, atd = screen_counts(model.hits)
            m = measured + atd
            out["screens"] = (f"{n} screen{'s' if n != 1 else ''} · {m} level{'s' if m != 1 else ''}", False)

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

        # sheet style
        d = Settings()
        same = all(getattr(s, k) == getattr(d, k) for k in STYLE_KEYS)
        out["style"] = ("Defaults" if same else "Custom", False)
        return out

    def _update_chips(self, s: Optional[Settings] = None) -> None:
        if not self.sections:
            return
        chips = self.chip_texts(s)
        for sec, key in zip(self.sections, ("line", "surfaces", "explorations", "depths", "screens", "scale",
                                            "style")):
            text, warn = chips[key]
            sec.setChip(text, warn)

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
        """Use `geom` (in `crs`) as the section line. Stored in a CRS with an authid (EPSG:4326 if needed)."""
        if not keep_origin:
            self._reversed_from = None
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
        """Swap the ends. A layer feature becomes a drawn (reversed) copy; the layer is never edited."""
        data = self.line_feature.currentData()
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
        layer.dataProvider().addFeatures([f])
        layer.updateExtents()
        layer.triggerRepaint()
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

    # ================================================================ teardown
    def cleanup(self) -> None:
        """Everything the dock put on the map or connected (plugin unload)."""
        self._timer.stop()
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
        self.feedback.remove()


def depth_sources_line(hits, s: Settings) -> str:
    """Where the tops and bottoms came from, e.g. "Tops: 5 ExploElev, 3 LIDAR · Bottoms: 2 BotElev,
    6 top − ExploDepth, 1 none" (rich text). Empty without explorations or without the line."""
    if not hits or not s.depth_line:
        return ""
    tops = Counter(h.top_source for h in hits)
    bottoms = Counter(getattr(h, "bottom_source", "none") for h in hits)
    top_names = {"field": s.top_field or "table", "dem": "LIDAR", "none": "none"}
    bottom_names = {"field": s.bottom_elev_field or "table",
                    "shifted": f"{s.bottom_elev_field or 'table'} shifted with the top",
                    "depth": f"top − {s.depth_field or 'depth'}", "none": "none"}

    def counts(c: Counter, names: dict) -> str:
        return ", ".join(f"{c[k]} {_esc(names[k])}" for k in names if c.get(k))

    return f"Tops: {counts(tops, top_names)} · Bottoms: {counts(bottoms, bottom_names)}"


CSV_COLUMNS = ["name", "type", "station_ft", "station", "offset_ft", "side", "direction", "x", "y",
               "ground_at_station_ft", "ground_at_point_ft", "top_ft", "top_source", "bottom_ft",
               "bottom_source", "depth_ft", "total_depth_ft", "screen_top_ft", "screen_bottom_ft", "water_levels",
               "in_dem_gap", "flags"]


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
                        "yes" if h.in_gap else "", "; ".join(h.flags or [])])


def _levels_text(levels) -> str:
    """ "652.8 measured 6/12/2025; 640.1 ATD" (highest first, as the model lists them)."""
    out = []
    for w in levels:
        parts = [f"{w.elev:.2f}".rstrip("0").rstrip("."), "ATD" if w.kind == "atd" else "measured"]
        if w.date:
            parts.append(w.date)
        out.append(" ".join(parts))
    return "; ".join(out)
