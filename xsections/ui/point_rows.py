"""The layer rows of the panel's Explorations and Other features sections (0.3.3, DESIGN.md decision 22; 0.3.6,
decision 27: the redesigned panel).

- TypeList: the ticked type values of a row's type field, with "plotted / in the layer" counts and a "(no value)"
  row for the NULL-or-empty value.
- PlottedList: the Plotted subsection of Explorations (0.3.6: its heading "PLOTTED" with Show all; the old title
  "Plotted explorations (N of M, K left off by you)" is the heading's tooltip): every exploration the rows choose on
  this section, grouped by row; unticking one leaves it off this section line (the dock keeps the list,
  Settings.hidden_points).
- PointRowList: the list of rows of the Explorations and Other features sections (moves, removes, renumbering; 0.3.6:
  the rows are layer cards, spaced for their bands by widgets.link_cards and painted open by their section's body,
  set_band_host).
- ExplorationRow: one explorations layer (own explorations, explorations by others, supply wells...), a layer card
  whose editor has the tabs Layer | Depths | Water (0.3.6, the mockup's grouping): its layer, legend name, look (Drawn
  in: Black, Gray or Color), label and type fields and types; the top, bottom and depth fields and "In elevation
  range" (next to Total depth, 0.3.5); the water fields and its table of water levels. For Color (0.3.4) its
  LayerStyleBox shows what XSections reads from the layer's own QGIS style (core.symbology.layer_style): the kind of
  style, up to four colour chips (those plotted on the section first) and how many are switched off. The fields it
  guessed from their names stay to be checked (the row's `guessed`, its "check" badge and card) until he says they
  look right (confirm_guess) or chooses them himself (0.3.6).
- OtherPointsRow: one layer of other features (0.3.6: a point, line or polygon layer: seeps, creeks, a site). A point
  or line row draws a symbol (SymbolCombo: the grouped drop-down of render.symbols) at each point, or where the
  section crosses a line, with its label and elevation rule; a polygon row a labelled bracket for each stretch of the
  section inside an area, in the frame or above it, with optional edge lines.

A row never loses what it was given: it keeps the cleaned dict of its last set_value (`_stored`, updated after each
edit), and while its layer is missing (removed, a moved file, an offline drive) it writes that dict back with only
its header widgets applied, instead of the empty field boxes. Everything the rows do in code is silent: `changed`
is emitted only for a user's edit.

0.3.6 (D14, D15): the dock's problems of a row (set_problems) and its guesses show on its check badge, its one amber
line and its check card (widgets.LayerCard.set_check); the card's buttons open the row on a tab (show_tab) or confirm
a guess (confirm_guess). The explanations under the controls are Verbose hints (widgets.Hint).

Imports: qgis, core.model, core.symbology (the layer's style, read only), core.explorations (text_number),
core.others (the feature kinds), render.scales (pure geometry and text), render.symbols (the catalogue),
ui.point_guess, ui.widgets and ui.symbol_icons; never ui.dock.
"""
from __future__ import annotations

import copy
from collections import Counter
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

from qgis.core import Qgis, QgsFeatureRequest, QgsProject, QgsVectorLayer
from qgis.gui import QgsCheckableComboBox, QgsColorButton, QgsFieldComboBox, QgsMapLayerComboBox
from qgis.PyQt.QtCore import QEvent, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import (QBrush, QColor, QFont, QFontMetrics, QIcon, QPainter, QPalette, QPen, QStandardItem,
                             QStandardItemModel)
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                                 QListView, QMenu, QScrollArea, QSizePolicy, QStyle, QStyledItemDelegate,
                                 QStyleOptionComboBox, QStylePainter, QToolButton, QTreeWidget, QTreeWidgetItem,
                                 QVBoxLayout, QWidget)

from ..core.explorations import text_number
from ..core.model import (AREA_COLOR_DEFAULT, DEFAULT_SHAPE, GUESS_KEYS, LOOK_GRAY, NO_ATD, NO_TYPES,
                          OTHER_POINT_DEFAULTS, OTHER_SIZE_MAX, OTHER_SIZE_MIN, POINT_LAYER_DEFAULTS, LayerStyle,
                          Settings, clean_other_point, clean_point_layer)
from ..core.others import feature_kind, feature_layer
from ..core.symbology import layer_style
from ..render.scales import pretty_label
from ..render.symbols import LEGACY_KEYS, SYMBOLS, grouped, usual_color
from . import point_guess as G
from .symbol_icons import symbol_icon
from .widgets import (MEDIUM, CardInfo, ClickableArea, ElidedLabel, ExploSwatch, Hint, LayerCard, Problem, RowTabs,
                      StyleChips, SubsectionHeading, SymbolSwatch, _esc, _field_combo, _narrow, _note,
                      _numeric_field_combo, _px_font, _segmented, _set_combo_data, _spin, field_box, field_kind,
                      link_button, link_cards, pair, set_field, theme_for)

EMPTY_LAYER = "(choose a point layer)"
EMPTY_FEATURE_LAYER = "(choose a layer)"   # 0.3.6: an Other features row without a layer (points, lines or areas)
NO_VALUE_TEXT = "(no value)"           # the NULL-or-empty type value ("" in Settings types)
BLACK_INK = "#111111"                  # the Black look's swatch
SCAN_LIMIT = 200_000                   # a type list counts the values of layers up to this size (else values only)
TEXT_SAMPLE = 50                       # a text field holds numbers when one of its first 50 values (not empty) ...
TEXT_ROWS = 2_000                      # ... in its first 2,000 rows is a number (number_texts, 0.3.5)
PLOTTED_MAX_H = 210                    # px, the Plotted explorations list
ROW_MENU_TIP = "Move up, move down, remove"     # a row's ⋯ button

# an Other features row's choices (0.3.6: the mockup's short names; the buttons' tooltips say the rest)
ELEV_CHOICES = [("Ground line", "line"), ("LIDAR", "lidar"), ("Field", "field")]
ELEV_TIPS = ["On the ground line drawn along the section, just touching it",
             "The LIDAR elevation at each point's own location", "An elevation field of the layer, ft"]
EMPTY_CHOICES = [("Line", "line"), ("LIDAR", "lidar"), ("Off", "off")]
EMPTY_TIPS = ["On the ground line", "LIDAR at the point", "Leave the point off"]
BRACKET_CHOICES = [("In the frame", "inside"), ("Above the frame", "above")]      # a polygon row (model.AREA_PLACES)
BRACKET_TIPS = ["Inside the frame, above the ground and the exploration labels", "In a row over the frame"]
EDGE_CHOICES = [("Off", "off"), ("To ground", "ground"), ("Full height", "full")]   # model.AREA_EDGES
EDGE_TIPS = ["No edge lines", "Dashed lines at the ends, down to the ground",
             "Dashed lines at the ends, the full height of the frame"]
BRACKET_STYLE_CHOICES = [("Solid", "solid"), ("Dashed", "dash")]                  # model.AREA_STYLES
BRACKET_STYLE_TIPS = ["Solid bracket", "Dashed bracket"]
KIND_WORDS = {"point": "points", "line": "lines", "polygon": "areas"}             # an Other row's subtitle
ROW_TIPS = {"point": "Draw these points", "line": "Draw a symbol where the section crosses these lines",
            "polygon": "Draw a bracket where the section runs through these areas"}
SWATCH_TIPS = {"point": "The symbol of these points", "line": "The symbol at each crossing",
               "polygon": "The bracket of these areas"}
COLOR_TIPS = {"point": "Color of the symbol", "line": "Color of the symbol",
              "polygon": "Color of the bracket and its label"}
LINE_HINT = "One symbol wherever the section line crosses a line of this layer."
AREA_HINT = ("One labelled bracket for each stretch of the section inside an area. Overlapping brackets stack, the "
             "longer one on top.")
# an exploration row's texts (0.3.5, his requests: "In elevation range" next to Total depth; the table's label, which
# he first read as the water table)
IN_RANGE_TEXT = "In elevation range"
IN_RANGE_SHORT = "In range"            # (only while the panel is too narrow for the whole text: 260 px)
IN_RANGE_TIP = ("Include this layer's explorations in the automatic elevation range. Unticked, deeper ones stop at the "
                "frame with an arrow and their TD.")
WL_TABLE_LABEL = "Water levels from a table (CSV, Excel…)"
WL_TABLE_TIP = ("A spreadsheet-style table (CSV, Excel sheet, or any layer; no geometry needed) with one row per "
                "water-level reading: the exploration's name, the level, and optionally its date and kind (measured "
                "or ATD).")
# 0.3.6: the tabs of an exploration row, its Verbose hints, the Water tab's tooltip while it has nothing to show
TABS = ("Layer", "Depths", "Water")
TAB_KEYS = ("layer", "depths", "water")       # show_tab's names (and the card actions open_layer ...)
RANGE_HINT = "Deeper ones stop at the frame with an arrow and their TD."
DEPTHS_HINT = "Top from the table, else LIDAR; bottom from the table, else top − depth."
NO_WATER_HINT = "This layer has no water-level or screen fields, so none are drawn for it."
NO_WATER_TIP = "No water-level or screen fields"
WATER_KEYS = ("screen_top_field", "screen_bottom_field", "wl_field", "atd_field", "wl_table_id")   # any: the Water tab
# the check card of a guess (D15): each guessed box's name, the tab its first box is on
GUESS_TITLE = "Fields were guessed"
FIELD_TERMS = {"label_field": "Label", "type_field": "Type", "top_field": "Top", "bottom_elev_field": "Bottom",
               "depth_field": "Total depth", "screen_top_field": "Screen top", "screen_bottom_field": "Screen bottom",
               "wl_field": "Measured level", "wl_date_field": "Measured date", "atd_field": "ATD level",
               "atd_date_field": "ATD date"}
DEPTH_KEYS = ("top_field", "bottom_elev_field", "depth_field")                  # on the Depths tab
LAYER_KEYS = ("label_field", "type_field")                                      # on the Layer tab (the rest: Water)

# the symbol drop-down (0.3.6, the mockup's sympop): each choice's description (its tooltip), verbatim from the approved
# mockup's catalogue (glyphs.js CAT)
SYMBOL_TIPS = {
    "spring": "A spring with a concentrated outflow, e.g. a contact spring at the base of advance outwash. The tail "
              "points downhill.",
    "thermal_spring": "A warm or mineralised spring: the spring with a small T (thermal) or M (mineral).",
    "stream": "Where the section crosses a creek, ditch or river channel; the label gives the name.",
    "pond": "A pond or stormwater/infiltration pond too narrow to draw as an area at section scale.",
    "wetland": "A wetland crossed by the section, e.g. a groundwater-discharge wetland (critical areas).",
    "well": "An Ecology well log or owner-reported well you are not plotting as an exploration.",
    "domestic": "A domestic supply well.",
    "public": "A Group A / Group B public water system well.",
    "irrigation": "An irrigation or water-right well.",
    "industrial": "An industrial or commercial supply well.",
    "monitoring": "A water-level or monitoring well shown as a point (projected from off the line, or levels only).",
    "observation": "An observation well of a supply system.",
    "pumping": "A pumped well in an aquifer test, or a dewatering / extraction well.",
    "artesian": "A well with head above the ground.",
    "uic": "A stormwater drywell or other Class V UIC well (Ch. 173-218 WAC), recharge or ASR well.",
    "unused": "An unused or capped well, no longer a water-level control point.",
    "destroyed": "A well decommissioned under WAC 173-160.",
    "gallery": "An infiltration gallery, trench or drain field crossing the section.",
    "gauge": "A USGS or Ecology gauging station. Solid: continuous record.",
    "staff": "A staff gauge or stage-measurement point.",
    "wq": "A surface-water, spring or seep sample point (label it SW-…). Never blue, so it is not read as a water "
          "level.",
    "sample": "A surface sample or field station, with its number.",
    "outcrop": "A bedrock exposure or outcrop of a mapped unit: a control point on the unit's surface.",
    "scarp": "Where the section crosses a landslide crown or scarp, often with seeps.",
    "benchmark": "A surveyed elevation (BM) used to check LIDAR or a top of casing. Its centre is the elevation.",
    "asterisk": "Seeps and anything else.",
    "circle": "Anything else.",
    "square": "Anything else.",
    "diamond": "Anything else.",
    "triangle": "Anything else.",
}
LEGACY_HEADER = "Kept from an older version"     # the drop-down's group of a legacy key the row holds (the star)
LEGACY_TIP = "Kept from an older version of XSections; no longer offered"
HEADER_ROLE = Qt.ItemDataRole.UserRole + 1       # True on a group header item of the drop-down


def reveal(w: QWidget) -> None:
    """Scroll `w` into view in its nearest scroll area, once the layouts have settled (a row opened from its card)."""
    def go() -> None:
        try:
            x = w.parentWidget()
            while x is not None and not isinstance(x, QScrollArea):
                x = x.parentWidget()
            if x is not None and x.widget() is not None and x.widget().isAncestorOf(w):
                x.ensureWidgetVisible(w, 0, 24)
        except RuntimeError:                   # (deleted meanwhile)
            pass
    QTimer.singleShot(0, go)


# ---------------------------------------------------------------- layers
def point_layer(layer_id: str) -> Optional[QgsVectorLayer]:
    """The valid point layer of the project with this id, else None (none chosen, removed, unreadable)."""
    lyr = QgsProject.instance().mapLayer(layer_id) if layer_id else None
    if isinstance(lyr, QgsVectorLayer) and lyr.isValid() and lyr.geometryType() == Qgis.GeometryType.Point:
        return lyr
    return None


def table_layer(layer_id: str) -> Optional[QgsVectorLayer]:
    """The valid vector layer (a table; geometry not needed) of the project with this id, else None."""
    lyr = QgsProject.instance().mapLayer(layer_id) if layer_id else None
    return lyr if isinstance(lyr, QgsVectorLayer) and lyr.isValid() else None


def layer_fields(layer: QgsVectorLayer) -> Tuple[List[Tuple[str, Optional[bool]]], Set[str]]:
    """((field name, kind) in layer order, the names of the primary-key fields); kind (widgets.field_kind, 0.3.5):
    True a number field, False a text field, None another kind (a date ...)."""
    flds = layer.fields()
    names = [(flds.at(i).name(), field_kind(flds.at(i))) for i in range(flds.count())]
    pk = {flds.at(i).name() for i in layer.primaryKeyAttributes() if 0 <= i < flds.count()}
    return names, pk


def number_texts(layer: QgsVectorLayer) -> Callable[[str], bool]:
    """Whether a text field of `layer` holds numbers (0.3.5, point_guess.TextOk: a number box guesses a text field only
    then): one of its first TEXT_SAMPLE values that are not empty, in its first TEXT_ROWS rows, is a plain number
    (core.explorations.text_number). Each field is read once, and only when asked (a guess would take it), so a
    typed layer's text columns (CDF_wells' Elevation_: "L Green R 2017", "Survey, NAVD 88") are never guessed."""
    seen: Dict[str, bool] = {}

    def ok(name: str) -> bool:
        if name not in seen:
            seen[name] = _has_number_text(layer, name)
        return seen[name]
    return ok


def _has_number_text(layer: QgsVectorLayer, name: str) -> bool:
    i = layer.fields().lookupField(name)
    if i < 0:
        return False
    req = (QgsFeatureRequest().setFlags(Qgis.FeatureRequestFlag.NoGeometry).setSubsetOfAttributes([i])
           .setLimit(TEXT_ROWS))
    n = 0
    try:
        for f in layer.getFeatures(req):
            t = _type_key(f.attribute(i)).strip()
            if not t:
                continue
            if text_number(t) is not None:
                return True
            n += 1
            if n >= TEXT_SAMPLE:
                break
    except Exception:                          # pragma: no cover - a provider that cannot be read: not guessed
        return False
    return False


def _type_key(value: Any) -> str:
    """A type value as the type list and Settings.types write it: NULL (and a NULL variant) and "" are ""."""
    if value is None:
        return ""
    is_null = getattr(value, "isNull", None)
    if callable(is_null) and is_null():
        return ""
    return str(value)


def _count_text(n: Optional[int]) -> str:
    return "–" if n is None else f"{n:,}"


class FitCheckBox(QCheckBox):
    """A check box that shows `short` while its text does not fit its width (the narrowest panel), its tooltip keeping
    the whole meaning; the text again as soon as it fits."""

    def __init__(self, text: str, short: str, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self._texts = (text, short)

    def _width_for(self, text: str) -> int:
        fm = self.fontMetrics()
        return self.sizeHint().width() - fm.horizontalAdvance(self.text()) + fm.horizontalAdvance(text)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        text, short = self._texts
        want = text if self._width_for(text) <= self.width() else short
        if self.text() != want:
            self.setText(want)


class FieldComboWithNone(QgsFieldComboBox):
    """A field box whose empty choice reads `text` while it is chosen (QgsFieldComboBox shows it blank)."""

    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._none_text = text
        self.setAllowEmptyFieldName(True)

    def emptyText(self) -> str:
        return self._none_text

    def paintEvent(self, e) -> None:
        if self.currentField():
            super().paintEvent(e)
            return
        p = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        opt.currentText = self._none_text
        p.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)
        p.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, opt)


def _shows(combo, layer) -> bool:
    """`combo` (a layer or field box) shows `layer` (None: none)."""
    cur = combo.currentLayer() if isinstance(combo, QgsMapLayerComboBox) else combo.layer()
    if layer is None:
        return cur is None
    return cur is not None and cur.id() == layer.id()


# ---------------------------------------------------------------- the type list
class TypeList(QTreeWidget):
    """The values of a row's type field, ticked when plotted. Column 0 the value ("(no value)" last, muted italic,
    for NULL or empty), column 1 "plotted / in the layer" (or the total before a model; small and muted, 0.3.6).
    Filling is silent: `changed` comes only from a user's tick (an item whose check state differs from its last known
    one). Frameless and transparent: its row puts it in a ListBox (0.3.6, the mockup's boxed list)."""

    changed = pyqtSignal()
    MAX_ROWS = 6
    ROW_H = 19                                 # px a row (0.3.6: the mockup's 18 px lines, 1 px apart)
    VALUE = Qt.ItemDataRole.UserRole           # the value ("" = no value)
    STATE = Qt.ItemDataRole.UserRole + 1       # the check state last known (True = ticked)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsTypeList")
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setIndentation(0)
        self.setFrameShape(QFrame.Shape.NoFrame)
        pal = self.palette()                     # frameless on the panel background (a stylesheet background
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))   # would spoil the check boxes)
        self.setPalette(pal)
        self.viewport().setAutoFillBackground(False)
        self.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        hdr = self.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.setToolTip("Types to plot. Right column: plotted / in the layer.")
        self.setFont(_px_font(self.font(), 11.5))
        self._count_font = _px_font(self.font(), 10.5)
        self._filling = 0
        self.totals: Counter = Counter()         # features by value ("" = no value); empty for a very big layer
        self._given: List[str] = []              # the checked list of the last fill (kept in its order)
        self._plotted: Optional[Counter] = None
        self.itemChanged.connect(self._on_item_changed)
        self.fit()

    # ---- filling (silent)
    def fill(self, layer: Optional[QgsVectorLayer], field: str, checked: Sequence[str]) -> None:
        """The values of `field` of `layer`, counted in one scan of the layer (no geometry, one attribute; above
        SCAN_LIMIT features the values only, without totals). Ticks: every value for [], none for [NO_TYPES], else
        the values listed ("" = (no value))."""
        self._filling += 1
        try:
            self.clear()
            self.totals = Counter()
            self._given = [str(v) for v in (checked or [])]
            idx = layer.fields().lookupField(field) if isinstance(layer, QgsVectorLayer) and field else -1
            values: List[str] = []
            has_none = False
            if idx >= 0:
                n = layer.featureCount()
                if 0 <= n <= SCAN_LIMIT:
                    req = QgsFeatureRequest().setFlags(Qgis.FeatureRequestFlag.NoGeometry).setSubsetOfAttributes([idx])
                    totals = self.totals
                    for f in layer.getFeatures(req):
                        totals[_type_key(f.attribute(idx))] += 1
                    values = [v for v in totals if v]
                    has_none = "" in totals
                else:
                    seen = {_type_key(v) for v in layer.uniqueValues(idx)}
                    has_none = "" in seen
                    values = [v for v in seen if v]
            wanted = set(self._given)
            none_ = self._given == [NO_TYPES]
            items = []
            muted = theme_for(self.palette()).muted
            for v in sorted(values, key=str.lower) + ([""] if has_none else []):
                item = QTreeWidgetItem([v or NO_VALUE_TEXT, ""])
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                on = not none_ and (not self._given or v in wanted)
                item.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
                item.setData(0, self.VALUE, v)
                item.setData(0, self.STATE, on)
                item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setSizeHint(0, QSize(0, self.ROW_H))
                item.setFont(1, self._count_font)
                item.setForeground(1, QBrush(muted))
                if not v:
                    f = QFont(self.font())
                    f.setItalic(True)
                    item.setFont(0, f)
                    item.setForeground(0, QBrush(muted))
                items.append(item)
            self.addTopLevelItems(items)
            self._write_counts()
        finally:
            self._filling -= 1
        self.fit()

    def set_plotted(self, plotted: Optional[Counter]) -> None:
        """Column 1: "plotted / in the layer" with a model's counts (Counter by type value), the total with None."""
        self._plotted = Counter(plotted) if plotted is not None else None
        self._filling += 1
        try:
            self._write_counts()
        finally:
            self._filling -= 1

    def _write_counts(self) -> None:
        for i in range(self.topLevelItemCount()):
            it = self.topLevelItem(i)
            v = it.data(0, self.VALUE)
            total = _count_text(self.totals[v]) if self.totals else "–"
            it.setText(1, f"{self._plotted.get(v, 0):,} / {total}" if self._plotted is not None else
                       (total if self.totals else ""))

    def check_all(self, on: bool) -> None:
        """Tick (or untick) every value, silently."""
        self._filling += 1
        try:
            for i in range(self.topLevelItemCount()):
                it = self.topLevelItem(i)
                it.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
                it.setData(0, self.STATE, bool(on))
        finally:
            self._filling -= 1

    # ---- reading
    def values(self) -> List[Tuple[str, bool]]:
        """(value, ticked) of every row, in the list's order."""
        return [(self.topLevelItem(i).data(0, self.VALUE),
                 self.topLevelItem(i).checkState(0) == Qt.CheckState.Checked) for i in range(self.topLevelItemCount())]

    def item_for(self, value: str) -> Optional[QTreeWidgetItem]:
        for i in range(self.topLevelItemCount()):
            if self.topLevelItem(i).data(0, self.VALUE) == value:
                return self.topLevelItem(i)
        return None

    def checked_types(self) -> List[str]:
        """Settings types from the ticks: every value ticked -> [], none -> [NO_TYPES], else the ticked values (in the
        order they were given when they are the same set, so a saved list reads back as saved)."""
        vals = self.values()
        if not vals:
            return []
        checked = [v for v, on in vals if on]
        if len(checked) == len(vals):
            return []
        if not checked:
            return [NO_TYPES]
        if set(checked) == set(self._given):
            return list(self._given)
        return checked

    def fit(self) -> None:
        """Show up to MAX_ROWS rows without scrolling; never taller than that."""
        n = self.topLevelItemCount()
        row = self.sizeHintForRow(0) if n else self.fontMetrics().height() + 4
        rows = max(1, min(n, self.MAX_ROWS))
        self.setFixedHeight(rows * max(row, 12) + 2 * self.frameWidth() + 2)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._filling or column != 0:
            return
        on = item.checkState(0) == Qt.CheckState.Checked
        if on == bool(item.data(0, self.STATE)):
            return
        self._filling += 1
        try:
            item.setData(0, self.STATE, on)
        finally:
            self._filling -= 1
        self.changed.emit()
class ListBox(QFrame):
    """A list in a box (0.3.6, the mockup's .typelist): the field colour with a 1 px field_line border, radius 3,
    painted (a stylesheet background would spoil the list's check boxes), the list inset 3 / 6 px. Disable the box,
    not the list, so a field label above it greys with it."""

    def __init__(self, inner: QWidget, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.inner = inner
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(0)
        lay.addWidget(inner)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _e) -> None:
        t = theme_for(self.palette())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(t.field_line, 1.0))
        p.setBrush(t.field)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 3.0, 3.0)
        p.end()


# ---------------------------------------------------------------- Plotted explorations
Entry = Tuple[str, int, str, str, bool]          # (layer id, fid, label, detail, plotted)


class PlottedList(QWidget):
    """The Plotted subsection of Explorations (0.3.6, D11; a Disclosure before): the heading "PLOTTED" with Show all
    (and, with Verbose, "N of M" beside it), then every exploration the rows choose on this section, grouped by row (a
    bold muted title), each with a tick, its label and "station · offset side". Unticking one emits toggled(layer id,
    fid, False); the dock keeps the list. Filling (set_entries, on every refresh) is silent. text() is the old title,
    "Plotted explorations (N of M, K left off by you)", also the heading's tooltip."""

    toggled = pyqtSignal(str, int, bool)        # a user's tick: (layer id, fid, plotted)
    showAllRequested = pyqtSignal()
    TITLE = "Plotted explorations"
    KEY = Qt.ItemDataRole.UserRole              # (layer id, fid) of an exploration item; None for a group title
    STATE = Qt.ItemDataRole.UserRole + 1        # the check state last known

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._filling = 0
        self._counts: Optional[Tuple[int, int]] = None      # (plotted, chosen); None: no model
        self._title = self.TITLE
        self.count_label = Hint("", rich=False)               # "N of M": a note beside the heading (Verbose)
        self.count_label.setWordWrap(False)
        self.count_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.count_label.setWanted(False)
        self.btn_show_all = link_button("Show all", "Plot every exploration you left off on this section")
        self.btn_show_all.setFont(_px_font(self.btn_show_all.font(), 11.0, MEDIUM))
        self.heading = SubsectionHeading("Plotted", right=[self.count_label, self.btn_show_all])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)    # a subsection that is not its body's first (widgets.Subsection)
        lay.setSpacing(8)
        lay.addWidget(self.heading)
        self.tree = QTreeWidget()
        self.tree.setObjectName("xsPlottedList")
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(0)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.tree.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.setMaximumHeight(PLOTTED_MAX_H)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        lay.addWidget(self.tree)
        self.empty_label = _note("Nothing chosen yet.")
        lay.addWidget(self.empty_label)
        self.hint = Hint("Untick one to leave it off this section only.")
        lay.addWidget(self.hint)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.btn_show_all.clicked.connect(self.showAllRequested.emit)
        self.set_entries(None)

    def text(self) -> str:
        """The title as 0.3.5's disclosure read: "Plotted explorations (N of M, K left off by you)"."""
        return self._title

    # ---- filling (silent)
    def set_entries(self, groups: Optional[Sequence[Tuple[str, Sequence[Entry]]]]) -> None:
        """One group per row: (title, [(layer id, fid, label, detail, plotted)]), shown in the order given (the dock
        sorts them by station). None (a failed build, no model): no entries and the plain title."""
        self._filling += 1
        self.tree.setUpdatesEnabled(False)
        try:
            self.tree.clear()
            t = theme_for(self.palette())
            muted = QBrush(t.muted)
            base = QFont(self.tree.font())
            title_font = QFont(base)
            title_font.setWeight(QFont.Weight.Bold)
            if title_font.pointSizeF() > 0:
                title_font.setPointSizeF(max(6.5, title_font.pointSizeF() * 0.84))
            items, titles = [], []
            plotted = chosen = 0
            for title, entries in groups or []:
                g = QTreeWidgetItem([str(title).upper(), ""])
                g.setFlags(Qt.ItemFlag.ItemIsEnabled)
                g.setFont(0, title_font)
                g.setForeground(0, muted)
                items.append(g)
                titles.append(g)
                for layer_id, fid, label, detail, on in entries:
                    it = QTreeWidgetItem([str(label), str(detail)])
                    it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                    it.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
                    it.setData(0, self.KEY, (str(layer_id), int(fid)))
                    it.setData(0, self.STATE, bool(on))
                    it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    it.setForeground(1, muted)
                    self._style(it, bool(on), base, muted)
                    items.append(it)
                    chosen += 1
                    plotted += bool(on)
            self.tree.addTopLevelItems(items)
            for g in titles:
                g.setFirstColumnSpanned(True)
            self._counts = (plotted, chosen) if groups is not None else None
        finally:
            self.tree.setUpdatesEnabled(True)
            self._filling -= 1
        has = self.tree.topLevelItemCount() > 0
        self.tree.setHidden(not has)
        self.empty_label.setHidden(has)
        self._fit()
        self._write_title()

    def _style(self, item: QTreeWidgetItem, on: bool, base: Optional[QFont] = None,
               muted: Optional[QBrush] = None) -> None:
        """A left-off exploration: muted and struck through."""
        f = QFont(base if base is not None else self.tree.font())
        f.setStrikeOut(not on)
        item.setFont(0, f)
        if on:
            item.setData(0, Qt.ItemDataRole.ForegroundRole, None)
        else:
            item.setForeground(0, muted if muted is not None else QBrush(theme_for(self.palette()).muted))

    def _fit(self) -> None:
        n = self.tree.topLevelItemCount()
        row = self.tree.sizeHintForRow(0) if n else self.tree.fontMetrics().height() + 4
        self.tree.setFixedHeight(min(PLOTTED_MAX_H, max(1, n) * max(row, 12) + 2 * self.tree.frameWidth() + 2))

    def _write_title(self) -> None:
        """The title (text(), the heading's tooltip) and, with a model, "N of M" beside the heading."""
        if self._counts is None:
            self._title, count = self.TITLE, ""
        else:
            n, m = self._counts
            k = m - n
            self._title = f"{self.TITLE} ({n} of {m}, {k} left off by you)" if k else f"{self.TITLE} ({n} of {m})"
            count = f"{n} of {m}"
        self.heading.setToolTip(self._title)
        self.count_label.setText(count)
        self.count_label.setToolTip(self._title)
        self.count_label.setWanted(bool(count))

    # ---- reading
    def counts(self) -> Optional[Tuple[int, int, int]]:
        """(N plotted, M chosen, K left off by you), None without a model."""
        if self._counts is None:
            return None
        n, m = self._counts
        return n, m, m - n

    def items(self) -> List[Entry]:
        """The explorations listed, in order: (layer id, fid, label, detail, plotted)."""
        out = []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            key = it.data(0, self.KEY)
            if key:
                out.append((key[0], key[1], it.text(0), it.text(1), it.checkState(0) == Qt.CheckState.Checked))
        return out

    def item_for(self, layer_id: str, fid: int) -> Optional[QTreeWidgetItem]:
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            key = it.data(0, self.KEY)
            if key and key[0] == layer_id and key[1] == int(fid):
                return it
        return None

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._filling or column != 0:
            return
        key = item.data(0, self.KEY)
        if not key:
            return
        on = item.checkState(0) == Qt.CheckState.Checked
        if on == bool(item.data(0, self.STATE)):
            return
        self._filling += 1
        try:
            item.setData(0, self.STATE, on)
            self._style(item, on)
            if self._counts is not None:
                n, m = self._counts
                self._counts = (n + (1 if on else -1), m)
        finally:
            self._filling -= 1
        self._write_title()
        self.toggled.emit(key[0], int(key[1]), on)


# ---------------------------------------------------------------- the row list
class PointRowList(QFrame):
    """The rows of the Explorations (or Other features) section, in panel order, made by `factory` (ExplorationRow or
    OtherPointsRow). `changed`: a row's user edit, a move or a remove (never set_rows or append); `rowsChanged`: rows
    added, moved or removed; `emptied`: the user removed the last row; `checksChanged` (0.3.6): a row's check badge
    appeared, went or changed (the dock recounts its section's count chip). The rows' ⋯ menus are wired here. 0.3.6:
    no frame, the rows are cards 4 px apart; link_cards spaces them for their bands after every add, move, remove and
    a row opening or closing, and the section body named by set_band_host paints the open ones (Flare)."""

    changed = pyqtSignal()
    rowsChanged = pyqtSignal()
    emptied = pyqtSignal()
    checksChanged = pyqtSignal()

    def __init__(self, factory: Callable[[], QWidget], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsPointList")
        self._factory = factory
        self._rows: List[Any] = []
        self._host: Optional[QWidget] = None
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(4)
        self.setHidden(True)

    @property
    def rows(self) -> List[Any]:
        return list(self._rows)

    def set_band_host(self, body: Optional[QWidget]) -> None:
        """The section body (widgets.SectionBody) that paints the rows' bands while they are open (0.3.6): every row,
        present and future, is watched by it (None: none)."""
        if body is self._host:
            return
        if self._host is not None:
            for row in self._rows:
                self._host.unwatch(row)
        self._host = body
        self._watch_rows()

    def band_host(self) -> Optional[QWidget]:
        return self._host

    def _watch_rows(self) -> None:
        if self._host is not None:
            for row in self._rows:
                self._host.watch(row)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._watch_rows()              # (placed in the body by now: the rows' ancestors in it are watched too)

    def set_rows(self, dicts: Sequence[dict], guess: bool = False) -> None:
        """Rows for `dicts` (replacing every row), silently; `guess`: their fields are guessed (set_value)."""
        for row in self._rows:
            self._drop(row)
        self._rows = []
        for d in dicts:
            self._add(d, guess)
        self._renumber()
        self.rowsChanged.emit()

    def append(self, d: Optional[dict] = None, open_editor: bool = False, guess: bool = False):
        """A new row for `d` at the end (silently: the caller decides whether it was the user), its editor open with
        `open_editor`. Returns the row."""
        row = self._add(d or {}, guess)
        self._renumber()
        if open_editor:
            row.set_editor_open(True)
        self.rowsChanged.emit()
        return row

    def move(self, row, step: int) -> None:
        if row not in self._rows:
            return
        i = self._rows.index(row)
        j = i + int(step)
        if not 0 <= j < len(self._rows) or j == i:
            return
        self._rows.insert(j, self._rows.pop(i))
        self._lay.removeWidget(row)
        self._lay.insertWidget(j, row)
        self._renumber()
        self.rowsChanged.emit()
        self.changed.emit()

    def remove(self, row) -> None:
        if row not in self._rows:
            return
        self._rows.remove(row)
        self._drop(row)
        self._renumber()
        self.rowsChanged.emit()
        if not self._rows:
            self.emptied.emit()
        self.changed.emit()

    def values(self) -> List[dict]:
        return [row.value() for row in self._rows]

    def uses_layer_ids(self) -> Set[str]:
        out: Set[str] = set()
        for row in self._rows:
            out |= row.uses_layer_ids()
        return out

    def _add(self, d: dict, guess: bool):
        row = self._factory()
        row.set_value(d, guess_fields=guess)
        row.changed.connect(self.changed.emit)
        row.moveRequested.connect(lambda step, r=row: self.move(r, step))
        row.removeRequested.connect(lambda r=row: self.remove(r))
        row.editorToggled.connect(self._link)
        row.checksChanged.connect(self.checksChanged.emit)
        self._rows.append(row)
        self._lay.addWidget(row)
        if self._host is not None:
            self._host.watch(row)
        return row

    def _drop(self, row) -> None:
        if self._host is not None:
            self._host.unwatch(row)
        row.set_removing(True)             # going: until it is deleted, its boxes' moves are no choices (layers
        row.blockSignals(True)             # removed meanwhile) and it signals nothing (this list may be gone)
        self._lay.removeWidget(row)
        row.setParent(None)
        row.deleteLater()

    def _link(self, *_args) -> None:
        link_cards(self._rows)

    def _renumber(self) -> None:
        n = len(self._rows)
        for i, row in enumerate(self._rows):
            row.set_position(i, n)
        link_cards(self._rows)
        if n == 0 or self.parentWidget() is not None:      # (never shown as a window of its own)
            self.setHidden(n == 0)


# ---------------------------------------------------------------- one row (shared by both kinds)
class _PointRow(LayerCard):
    """A layer card (0.3.6, widgets.LayerCard): [visible] [swatch] [name / subtitle] [check badge] [⋯], an amber
    problem line under them when the dock found one, and the editor that opens on a click on the row. Subclasses add
    their own editor fields and say which keys the header holds (_header_value) and which depend on the layer's
    fields (_fields_value)."""

    changed = pyqtSignal()
    moveRequested = pyqtSignal(int)          # -1 up, +1 down
    removeRequested = pyqtSignal()
    layerSwapped = pyqtSignal(str, str, str)  # a user's layer choice: (old layer id, new layer id, old layer's name)
    DEFAULTS: Dict[str, Any] = {}
    ROW_TIP = "Draw this layer"
    LAYER_FILTERS = Qgis.LayerFilter.PointLayer       # the layers its layer box lists
    EMPTY_TEXT = EMPTY_LAYER                          # its empty choice, and the name of a row without a layer
    EDITOR_MARGINS = (9, 8, 8, 11)                    # the editor's contents margins, px

    def __init__(self, data: Optional[dict] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsPointRow")
        self.setProperty("first", False)
        self._filling = 0
        self._removing = False             # the project is removing layers: the boxes' moves are not choices
        self._stored: dict = self._clean({})
        self._last_name = ""               # the name the row's layer had while it was in the project
        self._guessed: List[str] = []      # 0.3.6: the boxes guessed from the field names that he has not checked
        self._problems: List[Problem] = []  # 0.3.6: the dock's problems of this row (set_problems)
        self._counts: Optional[Tuple[Counter, int]] = None
        self._ends = (pretty_label("A"), pretty_label("A'"))

        line = self.header
        self.visible_box = QCheckBox(line)
        self.visible_box.setToolTip(self.ROW_TIP)
        self.swatch = self._make_swatch()
        self.swatch.setParent(line)
        self.name_area = ClickableArea(line)
        self.name_area.setToolTip("Show or hide this layer's settings")
        na = QVBoxLayout(self.name_area)
        na.setContentsMargins(0, 0, 0, 0)
        na.setSpacing(0)
        self.name_label = ElidedLabel("", parent=self.name_area)
        self.sub_label = ElidedLabel("", small=True, parent=self.name_area)
        na.addWidget(self.name_label)
        na.addWidget(self.sub_label)
        self.name_area.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.menu_btn = QToolButton(line)
        self.menu_btn.setObjectName("xsRowMenu")
        self.menu_btn.setText("⋯")
        self.menu_btn.setToolTip(ROW_MENU_TIP)
        self.menu_btn.setFixedSize(22, 20)
        self.menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.menu_btn)
        self.act_up = menu.addAction("Move up")
        self.act_down = menu.addAction("Move down")
        menu.addSeparator()
        self.act_remove = menu.addAction("Remove")
        self.menu_btn.setMenu(menu)
        self._place_header(self.visible_box, self.swatch, self.name_area, self.menu_btn)

        self.editor.setObjectName("xsSurfaceEditor")
        ed = QVBoxLayout(self.editor)
        ed.setContentsMargins(*self.EDITOR_MARGINS)
        ed.setSpacing(8)
        self.layer_combo = QgsMapLayerComboBox(self.editor)
        self.layer_combo.setFilters(self.LAYER_FILTERS)
        self.layer_combo.setAllowEmptyLayer(True, self.EMPTY_TEXT)
        _narrow(self.layer_combo)
        self.name_edit = QLineEdit(self.editor)
        self.name_edit.setToolTip("Name in the legend and the panel (empty: the layer name)")
        self.label_field = _field_combo("Field written as each point's label", allow_empty=False)
        self.type_field = self._make_type_field()
        self.type_list = TypeList(self.editor)
        self.btn_types_all = link_button("All", "Plot every type")
        self.btn_types_none = link_button("None", "Plot no type")
        self._types_dot = QLabel("·")
        self._types_dot.setObjectName("xsMuted")
        self.type_box = ListBox(self.type_list)
        self._build_editor(ed)

        self.name_area.clicked.connect(self.toggle_editor)
        self.act_up.triggered.connect(lambda: self.moveRequested.emit(-1))
        self.act_down.triggered.connect(lambda: self.moveRequested.emit(1))
        self.act_remove.triggered.connect(self.removeRequested.emit)
        self.visible_box.toggled.connect(self._on_header_edit)
        self.name_edit.textChanged.connect(self._on_header_edit)
        self.layer_combo.layerChanged.connect(self._on_layer_combo)
        self.layer_combo.activated.connect(self._on_layer_combo)
        self.label_field.fieldChanged.connect(self._on_field_edit)
        self.type_field.fieldChanged.connect(self._on_type_field_edit)
        self.type_list.changed.connect(self._on_field_edit)
        self.btn_types_all.clicked.connect(lambda: self._check_all_types(True))
        self.btn_types_none.clicked.connect(lambda: self._check_all_types(False))
        self._connect_editor()
        self.set_value(data or {})

    # ---- hooks (subclasses)
    def _make_swatch(self) -> QWidget:
        raise NotImplementedError

    def _make_type_field(self) -> QgsFieldComboBox:
        return _field_combo("Field of the types to plot (empty: every point)")

    def _build_editor(self, ed: QVBoxLayout) -> None:
        raise NotImplementedError

    def _connect_editor(self) -> None:
        pass

    def _clean(self, d: dict) -> dict:
        raise NotImplementedError

    def _resolve(self, layer_id: str) -> Optional[QgsVectorLayer]:
        """The row's layer of the project with this id, valid and of a kind the row draws, else None."""
        return point_layer(layer_id)

    def _field_boxes(self) -> Sequence[Tuple[str, QgsFieldComboBox, bool, bool]]:
        """(key, box, numbers only, may be empty) of the layer's field boxes."""
        raise NotImplementedError

    def _guess(self, fields, pk, layer_name: str, d: dict, guess_fields: bool,
               text_ok=None) -> Tuple[dict, str, List[str]]:
        """(the field keys, the guess's hint, the keys it guessed from the field names)."""
        raise NotImplementedError

    def _header_value(self) -> dict:
        return dict(visible=self.visible_box.isChecked(), name=self.name_edit.text().strip())

    def _set_header(self, d: dict) -> None:
        self.visible_box.setChecked(d["visible"])
        self.name_edit.setText(d["name"])

    def _fields_value(self) -> dict:
        out = {key: box.currentField() for key, box, _num, _empty in self._field_boxes()}
        out["types"] = self.type_list.checked_types() if out.get("type_field") else []
        if "guessed" in self.DEFAULTS:
            out["guessed"] = list(self._guessed)
        return out

    def _resolved(self, d: dict, layer: Optional[QgsVectorLayer]) -> None:
        """The row `d` is being shown with `layer` (None: missing or none), before its header (inside set_value)."""

    def _apply_extra(self, d: dict, guess: dict, guess_table: bool) -> None:
        """Show the subclass's other keys of `d` (inside set_value, silently)."""

    def _new_layer_keys(self, d: dict, layer: Optional[QgsVectorLayer]) -> None:
        """Keys a user's new layer re-guesses (in place)."""

    def _guess_card(self, d: dict) -> Optional[CardInfo]:
        """The check card's block for the row's guessed fields (None: nothing to check)."""
        return None

    def _sync_enabled(self) -> None:
        on = bool(self.type_field.currentField())
        for w in (self.type_box, self.btn_types_all, self.btn_types_none):
            w.setEnabled(on)

    def refresh_labels(self) -> None:
        raise NotImplementedError

    # ---- value
    def _frozen(self) -> bool:
        """The field boxes do not hold this row's fields: its layer is missing (or none is chosen), the project is
        removing layers, or the boxes were not filled for the layer yet (it just came back): value() then writes the
        stored fields back."""
        if self._removing:
            return True
        lyr = self.layer()
        return lyr is None or not _shows(self.layer_combo, lyr) or not _shows(self.label_field, lyr)

    def value(self) -> dict:
        """The row as a cleaned dict, in its defaults' key order. While the row's layer is missing, the stored dict
        with only the header widgets applied."""
        out = copy.deepcopy(self._stored)
        out.update(self._header_value())
        if not self._frozen():
            out["layer_id"] = self.layer_combo.currentLayer().id()
            out.update(self._fields_value())
        return self._clean(out)

    def stored(self) -> dict:
        """A copy of the stored dict (the last set_value, updated after each user edit)."""
        return copy.deepcopy(self._stored)

    def set_value(self, d: dict, guess_fields: bool = False) -> None:
        """Show the row `d` (cleaned), silently: fields before types; a saved field the layer has is kept, a saved
        empty optional field stays empty unless `guess_fields`, a saved field the layer lacks is guessed. A layer
        that does not resolve keeps every key (value() writes them back)."""
        self._apply(d, guess_fields, guess_table=guess_fields)

    def _apply(self, d: dict, guess_fields: bool, guess_table: bool) -> None:
        d = self._clean(d or {})
        lyr = self._resolve(d["layer_id"])
        self._filling += 1
        try:
            self._stored = copy.deepcopy(d)
            self._resolved(d, lyr)
            self.layer_combo.setLayer(lyr)
            self._set_header(d)
            for _key, box, _num, _empty in self._field_boxes():
                box.setLayer(lyr)
            guess: dict = {}
            keys: List[str] = []
            if lyr is not None:
                fields, pk = layer_fields(lyr)
                guess, _hint, keys = self._guess(fields, pk, lyr.name(), d, guess_fields, text_ok=number_texts(lyr))
                for key, box, numeric, may_be_empty in self._field_boxes():
                    set_field(box, guess.get(key, ""), (), allow_empty=may_be_empty, numeric=numeric,
                              keep_empty=True, pk=pk)
                self.type_list.fill(lyr, self.type_field.currentField(), d["types"])
            else:
                self.type_list.fill(None, "", d["types"])
            # the boxes still to check (0.3.6): a fresh guess's; else those stored, but for a box that is empty now,
            # and those guessed again just now (a saved field the layer lacks: renamed, or another layer taken back)
            stored = list(d.get("guessed") or [])
            boxes = {key: box for key, box, _num, _empty in self._field_boxes()}
            if lyr is None:
                self._guessed = stored
            elif guess_fields:
                self._guessed = list(keys)
            else:
                self._guessed = [k for k in GUESS_KEYS
                                 if k in boxes and boxes[k].currentField() and (k in stored or k in keys)]
            self._apply_extra(d, guess, guess_table)
            if self._counts is not None:
                self.type_list.set_plotted(self._counts[0])
            if not self._frozen():
                self._stored = self.value()       # with the guesses
        finally:
            self._filling -= 1
        self._sync_enabled()
        self.refresh_labels()

    # ---- the layer
    def layer(self) -> Optional[QgsVectorLayer]:
        return self._resolve(self._stored.get("layer_id", ""))

    def is_missing(self) -> bool:
        """A layer was chosen and it no longer resolves to a valid layer of the project that the row can draw."""
        return bool(self._stored.get("layer_id")) and self.layer() is None

    def uses_layer_ids(self) -> Set[str]:
        """Its layer (and table) ids, missing or not."""
        return {self._stored.get("layer_id", "")} - {""}

    def last_layer_name(self) -> str:
        """The name its layer had while it was in the project this session, valid or kept unavailable by QGIS (a moved
        or offline file); "" never seen."""
        return self._last_name

    def take_layer(self, layer: QgsVectorLayer) -> None:
        """Take `layer` (the same layer added again: a new id) with every stored key, silently."""
        self._apply(dict(self.value(), layer_id=layer.id()), guess_fields=False, guess_table=False)

    def set_removing(self, on: bool) -> None:
        self._removing = bool(on)
        if not on:
            self.sync_layer()

    def sync_layer(self) -> None:
        """Show the stored layer (and table) again, silently: after layers were removed (the boxes moved on by
        themselves) or added (a missing one may be back, or repaired with Change Data Source)."""
        if self._removing:
            return
        if self._needs_sync():
            self._apply(self.value(), guess_fields=False, guess_table=False)
        else:
            self.refresh_labels()

    def _needs_sync(self) -> bool:
        lyr = self.layer()
        return not (_shows(self.layer_combo, lyr) and _shows(self.label_field, lyr))

    def reload_values(self) -> None:
        """Refresh: read the type values again (keeping the ticks), silently."""
        if self._frozen():
            return
        self._filling += 1
        try:
            self.type_list.fill(self.layer(), self.type_field.currentField(), self.type_list.checked_types())
            if self._counts is not None:
                self.type_list.set_plotted(self._counts[0])
        finally:
            self._filling -= 1
        self.refresh_labels()

    # ---- editor (editor_open, toggle_editor: LayerCard's)
    def set_editor_open(self, on: bool) -> None:
        """Open or close the editor; while open the name and its subtitle are semibold (the mockup's open row)."""
        super().set_editor_open(on)
        self.sub_label.setBold(bool(on))

    def show_tab(self, which: Union[str, int, None] = None) -> None:
        """Open the row's editor and scroll it into view (a check card's button; ExplorationRow: on the tab `which`,
        "layer" | "depths" | "water" or 0-2)."""
        self.set_editor_open(True)
        reveal(self)

    def set_position(self, index: int, count: int) -> None:
        self.act_up.setEnabled(index > 0)
        self.act_down.setEnabled(index < count - 1)
        self.setProperty("first", index == 0)      # (0.3.6: link_cards spaces the cards; no stylesheet rule)

    def set_end_labels(self, a: str, b: str) -> None:
        """The section's end labels (with primes) for the row's hints."""
        self._ends = (a or "", b or "")
        self.refresh_labels()

    def set_counts(self, plotted: Optional[Counter], left_off: int = 0) -> None:
        """The model's counts for this row (Counter by type value of its plotted points, crossings or pieces; None
        before a model or on a failed build), silently."""
        self._counts = (Counter(plotted), int(left_off)) if plotted is not None else None
        self.type_list.set_plotted(self._counts[0] if self._counts is not None else None)
        self.refresh_labels()

    # ---- checks (0.3.6, D14, D15)
    def set_problems(self, problems: Sequence[Problem]) -> None:
        """The dock's problems of this row (ui.problems): the badge counts them, the first one's line shows under the
        header whatever Verbose is, and each is a block of the check card (with the row's guess, if any)."""
        self._problems = list(problems or ())
        self._sync_check()

    def problems(self) -> List[Problem]:
        return list(self._problems)

    def _sync_check(self, d: Optional[dict] = None) -> None:
        self.set_check(self._problems, self._guess_card(d if d is not None else self.value()))

    def guessed(self) -> List[str]:
        """The boxes guessed from the field names that he has not checked yet (the row's `guessed`)."""
        return list(self._guessed)

    def confirm_guess(self) -> None:
        """"Looks right" on the check card (D15): the guessed fields are his choice now; the guess goes for good (the
        row's `guessed` is saved with the project)."""
        if not self._guessed and not self._stored.get("guessed"):
            return
        self._guessed = []
        if "guessed" in self._stored:
            self._stored["guessed"] = []
        self._user_edit()

    def _on_card_action(self, key: str) -> None:
        """A button of this row's check card: open the row (on a tab), or "Looks right"."""
        if key == "looks_right":
            self.confirm_guess()
        elif key == "open":
            self.show_tab()
        elif key.startswith("open_") and key[5:] in TAB_KEYS:
            self.show_tab(key[5:])

    def _drop_checked(self) -> None:
        """A user's edit of the field boxes: a guessed box he changed holds his choice now (nothing to check)."""
        if not self._guessed:
            return
        boxes = {key: box for key, box, _num, _empty in self._field_boxes()}
        self._guessed = [k for k in self._guessed
                         if k not in boxes or boxes[k].currentField() == self._stored.get(k, "")]

    # ---- shared label pieces
    def _show_name(self, d: dict) -> None:
        lyr = self.layer()
        if lyr is not None:
            self._last_name = lyr.name()
            name = d["name"] or lyr.name()
        elif self.is_missing():
            # an unavailable layer QGIS kept in the project (a moved or offline file): it is still there under its
            # name, so the same file added again is taken back with every stored key (the dock's _on_layers_added)
            raw = QgsProject.instance().mapLayer(d["layer_id"]) if d["layer_id"] else None
            if raw is not None and raw.name():
                self._last_name = raw.name()
            name = d["name"] or self._last_name or "Layer not in the project"
        else:
            name = d["name"] or self.EMPTY_TEXT
        self.name_label.setText(name)
        self.name_label.setWarn(self.is_missing())
        self.name_label.setMuted(lyr is None and not self.is_missing())
        self.name_edit.setPlaceholderText((lyr.name() if lyr is not None else self._last_name) or "Name in the legend")

    def _types_part(self, d: dict) -> str:
        if not d["type_field"]:
            return "all points"
        vals = [(v, on) for v, on in self.type_list.values() if v]
        return f"{sum(1 for _v, on in vals if on)} of {len(vals)} types"

    # ---- user edits
    def _user_edit(self) -> None:
        self._stored = self.value()
        self._sync_enabled()
        self.refresh_labels()
        self.changed.emit()

    def _on_header_edit(self, *args) -> None:
        if self._filling:
            return
        self._user_edit()

    def _on_field_edit(self, *args) -> None:
        if self._filling or self._frozen():
            return
        self._drop_checked()
        self._user_edit()

    def _on_type_field_edit(self, *args) -> None:
        if self._filling or self._frozen():
            return
        self._drop_checked()
        self._filling += 1
        try:
            self.type_list.fill(self.layer(), self.type_field.currentField(), [])
            if self._counts is not None:
                self.type_list.set_plotted(self._counts[0])
        finally:
            self._filling -= 1
        self._user_edit()

    def _check_all_types(self, on: bool) -> None:
        if self._frozen():
            return
        before = self.type_list.checked_types()
        self.type_list.check_all(on)
        if self.type_list.checked_types() != before:
            self._user_edit()

    def _on_layer_combo(self, *args) -> None:
        """The user chose a layer (or none) in the row."""
        if self._filling or self._removing:
            return
        layer = self.layer_combo.currentLayer()
        new_id = layer.id() if layer is not None else ""
        if new_id == self._stored.get("layer_id", ""):        # its own layer again: show what it stored
            if self._needs_sync():
                self.sync_layer()
            return
        old = self.value()
        old_id, old_name = old["layer_id"], self._last_name
        d = dict(old, layer_id=new_id, types=[])
        self._new_layer_keys(d, layer if isinstance(layer, QgsVectorLayer) else None)
        self._apply(d, guess_fields=True, guess_table=False)
        if old_id != new_id:
            self.layerSwapped.emit(old_id, new_id, old_name)
        self._user_edit()


# ---------------------------------------------------------------- Drawn in: Color, the layer's style (0.3.4)
LOOK_HINT = ("Black by default, like your own explorations. Gray sets this layer apart; Color takes each "
             "exploration's color from this layer's style in QGIS.")
# the Verbose hint under Drawn in (0.3.6; LOOK_HINT is the field name's tooltip)
LOOK_NOTE = ("Black like your own explorations; Gray sets a layer apart; Color takes each exploration’s "
             "color from the layer’s style in QGIS.")
STYLE_HEAD = "From the layer's style in QGIS: "
STYLE_FOOT = "Change them in Layer Properties &gt; Symbology; the sheet follows."
STYLE_CHIPS_MAX = 4                    # chips shown; the rest are "+ N more"
SINGLE_CHIP = "every exploration"      # the one chip of a single-symbol style


def _counted(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


class LayerStyleBox(QFrame):
    """What a Color row reads from its layer's QGIS style (the mockup's style box): a head naming the kind of style
    ("From the layer's style in QGIS: Categorized by ExploType · 13 categories"), up to four colour chips (the items
    switched on, those plotted on the section first, then the legend's order) and "+ N more", a muted line for the
    items switched off in QGIS (their explorations are drawn in black), and the foot "Change them in Layer
    Properties > Symbology; the sheet follows." for a style of several items (0.3.6: a Verbose hint, and the
    box's tooltip)."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsStyleBox")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(7, 5, 7, 5)
        lay.setSpacing(4)
        self.head = _note("")
        self.head.setTextFormat(Qt.TextFormat.RichText)
        self.chips = StyleChips(self)
        self.off_note = _note("")
        self.off_note.hide()
        self.foot = Hint(STYLE_FOOT)                        # an explanation: Verbose only (D13)
        self.foot.setWanted(False)
        for w in (self.head, self.chips, self.off_note, self.foot):
            lay.addWidget(w)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setToolTip(STYLE_FOOT.replace("&gt;", ">"))
        self.set_style(None)

    @staticmethod
    def head_text(style: Optional[LayerStyle], missing: bool = False) -> str:
        if style is None:
            return STYLE_HEAD + ("the layer is not in the project." if missing else "no layer chosen.")
        n = len(style.items)
        if style.kind == "single":
            what = "<b>Single symbol</b>"
        elif style.kind == "categorized":
            what = f"<b>Categorized by {_esc(style.field)}</b> · {_counted(n, 'category', 'categories')}"
        elif style.kind == "graduated":
            what = f"<b>Graduated by {_esc(style.field)}</b> · {_counted(n, 'range', 'ranges')}"
        elif style.kind == "rule":
            what = f"<b>Rule-based</b> · {_counted(n, 'rule', 'rules')}"
        elif style.kind == "other" and n:
            what = f"<b>{_esc(style.name or 'Other')}</b>"
        else:
            what = "no symbols (the lines are drawn in black)"
        return STYLE_HEAD + what

    @staticmethod
    def chips_for(style: Optional[LayerStyle], plotted: Optional[Set[str]] = None
                  ) -> Tuple[List[Tuple[str, str]], int]:
        """([(label, colour)] of the chips, how many more are on): see the class docstring."""
        if style is None or not style.items or style.kind == "none":
            return [], 0
        if style.kind == "single":
            return [(SINGLE_CHIP, style.items[0].color)], 0
        on = [it for it in style.items if it.on]
        keys = set(plotted or ())
        order = [it for it in on if it.key in keys] + [it for it in on if it.key not in keys]
        shown = order[:STYLE_CHIPS_MAX]
        return [(it.label, it.color) for it in shown], len(order) - len(shown)

    def set_style(self, style: Optional[LayerStyle], missing: bool = False,
                  plotted: Optional[Set[str]] = None) -> None:
        """Show `style` (None: no layer; `missing`: its layer is not in the project); `plotted`: the item keys of the
        row's explorations on the section (None before a model)."""
        if missing:
            style = None
        self.head.setText(self.head_text(style, missing))
        items, more = self.chips_for(style, plotted)
        self.chips.set_items(items, more)
        self.chips.setHidden(not items)
        off = sum(1 for it in style.items if not it.on) if style is not None else 0
        self.off_note.setText(f"{off} switched off in QGIS: their explorations are drawn in black." if off else "")
        self.off_note.setHidden(not off)
        several = style is not None and style.kind in ("categorized", "graduated", "rule", "other") \
            and bool(style.items)
        self.foot.setWanted(several)


# ---------------------------------------------------------------- an explorations row
class ExplorationRow(_PointRow):
    """One explorations layer: [visible] [line swatch] [name / "label · k of n types · look · table"] [badge] [⋯] over
    the guess's warn hint (Verbose), the tabs Layer | Depths | Water (0.3.6, D4: the mockup's grouping) and its editor,
    one pane per tab: Layer: the layer, legend name and look, the style box, the label and type fields, types; Depths:
    the top, bottom and depth fields and "In elevation range"; Water: the water and screen fields and the table of
    water levels. The Water tab is dimmed (still a tab) while the layer has no water-level or screen fields."""

    DEFAULTS = POINT_LAYER_DEFAULTS
    EDITOR_MARGINS = (9, 10, 8, 11)
    # (depth line, top mode, screens) until the dock's set_shared: the Settings defaults
    _shared = (bool(Settings().depth_line), str(Settings().top_mode), bool(Settings().screens))
    # the layer's QGIS style as last read (refresh_style; None without the layer), and the style item keys of the
    # row's explorations plotted on the section (set_plotted_styles; None before a model)
    _style: Optional[LayerStyle] = None
    _plotted_keys: Optional[Set[str]] = None

    def _make_swatch(self) -> QWidget:
        sw = ExploSwatch(BLACK_INK)
        sw.setToolTip("How this layer is drawn")
        return sw

    def _clean(self, d: dict) -> dict:
        return clean_point_layer(d) or copy.deepcopy(POINT_LAYER_DEFAULTS)

    def _pane(self, ed: QVBoxLayout) -> QWidget:
        """One tab's pane of the editor (only the current one is shown: the editor's height follows it)."""
        w = QWidget(self.editor)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        ed.addWidget(w)
        return w

    def _build_editor(self, ed: QVBoxLayout) -> None:
        # over the editor, under the header: the guess's sentence (a warn hint, Verbose) and the tabs (both open only)
        self.guess_hint = Hint("", warn=True)
        self.guess_hint.setContentsMargins(9, 4, 8, 2)
        self.guess_hint.setWanted(False)
        self.tabs = RowTabs(self)
        for text in TABS:
            self.tabs.addTab(text)
        self.tabs.hide()
        i = self.card_layout.indexOf(self.editor)
        self.card_layout.insertWidget(i, self.guess_hint)
        self.card_layout.insertWidget(i + 1, self.tabs)
        self.pane_layer, self.pane_depths, self.pane_water = (self._pane(ed) for _ in TABS)
        self.pane_depths.hide()
        self.pane_water.hide()

        # Layer
        lay = self.pane_layer.layout()
        lay.addWidget(field_box("Layer", self.layer_combo))
        self.look_seg = _segmented([("Black", "black"), ("Gray", "gray"), ("Color", "color")],
                                   ["Black, like your own explorations", "Gray, to set this layer apart",
                                    "Each exploration in its color in this layer's style in QGIS"])
        self.look_seg.setToolTip(LOOK_HINT)
        lay.addWidget(pair(field_box("Legend", self.name_edit), field_box("Drawn in", self.look_seg, tip=LOOK_HINT),
                           (5, 4)))
        self.look_hint = Hint(LOOK_NOTE)
        lay.addWidget(self.look_hint)
        self.style_box = LayerStyleBox(self.editor)          # Color: what is read from the layer's style
        self.style_box.hide()
        lay.addWidget(self.style_box)
        lay.addWidget(pair(field_box("Label", self.label_field), field_box("Type", self.type_field)))
        lay.addWidget(field_box("Types", self.type_box, links=[self.btn_types_all, self._types_dot,
                                                               self.btn_types_none]))

        # Depths
        lay = self.pane_depths.layout()
        self.top_field = _numeric_field_combo("Top (collar or ground) elevation of each exploration, ft. Optional: "
                                              "LIDAR is used where it is empty.")
        self.bottom_elev_field = _numeric_field_combo("Bottom elevation of each exploration, ft. Optional: where it "
                                                      "is empty, the bottom is the top minus the total depth.")
        lay.addWidget(pair(field_box("Top elevation", self.top_field),
                           field_box("Bottom elevation", self.bottom_elev_field)))
        self.depth_field = _numeric_field_combo("Total depth below the top, ft. Optional: used where there is no "
                                                "bottom elevation, and for the TD label.")
        # next to Total depth (0.3.5, his request: below the table it read as a water setting)
        self.in_range_box = FitCheckBox(IN_RANGE_TEXT, IN_RANGE_SHORT)
        self.in_range_box.setToolTip(IN_RANGE_TIP)
        self.depth_pair = pair(field_box("Total depth", self.depth_field), self.in_range_box)
        lay.addWidget(self.depth_pair)
        self.range_hint = Hint(RANGE_HINT)
        self.range_hint.setWanted(False)
        lay.addWidget(self.range_hint)
        self.depths_hint = Hint(DEPTHS_HINT)
        lay.addWidget(self.depths_hint)

        # Water
        lay = self.pane_water.layout()
        self.wl_field = _numeric_field_combo("Measured water level: elevation or depth, ft (see Levels are). Drawn "
                                             "as an open triangle joined to the middle of the screen.")
        self.wl_date_field = _field_combo("Date of the measured water level (any field type). Optional.")
        lay.addWidget(pair(field_box("Measured level", self.wl_field), field_box("Date", self.wl_date_field)))
        self.atd_field = _numeric_field_combo("Water level at the time of drilling (ATD): elevation or depth, ft (see "
                                              "Levels are). Drawn as a filled triangle on the exploration line.")
        self.atd_date_field = _field_combo("Date of the ATD water level, usually the drilling date (any field type). "
                                           "Optional.")
        lay.addWidget(pair(field_box("ATD level", self.atd_field), field_box("Date", self.atd_date_field)))
        self.screen_top_field = _numeric_field_combo("Top of the well screen (depth or elevation, see Screens are). "
                                                     "Optional.")
        self.screen_bottom_field = _numeric_field_combo("Bottom of the well screen (depth or elevation, see Screens "
                                                        "are). Optional.")
        lay.addWidget(pair(field_box("Screen top", self.screen_top_field),
                           field_box("Screen bottom", self.screen_bottom_field)))
        self.wl_values = _segmented([("Elevations", "elevation"), ("Depths", "depth")],
                                    ["Water levels are elevations, ft",
                                     "Water levels are depths below the top of the exploration, ft"])
        self.wl_values.setToolTip("Applies to the measured and ATD fields and to the table of water levels")
        # Elevations | Depths, as Levels are (0.3.5; the stored values and the default "depth" unchanged)
        self.screen_values = _segmented([("Elevations", "elevation"), ("Depths", "depth")],
                                        ["Elevations, ft", "Feet below the top of the exploration"])
        lay.addWidget(pair(field_box("Levels are", self.wl_values), field_box("Screens are", self.screen_values)))
        self.wl_table = QgsMapLayerComboBox(self.editor)
        self.wl_table.setFilters(Qgis.LayerFilter.VectorLayer)
        self.wl_table.setAllowEmptyLayer(True, "(none)")
        self.wl_table.setToolTip(WL_TABLE_TIP)
        _narrow(self.wl_table)
        lay.addWidget(field_box(WL_TABLE_LABEL, self.wl_table))
        self.wl_table_name_field = _field_combo("Exploration name: matches this layer's label field (case and spaces "
                                                "ignored)", allow_empty=False)
        self.wl_table_elev_field = _field_combo("Water level: elevation or depth, ft (as set in Levels are)",
                                                numeric=True, allow_empty=False)
        self.wl_table_date_field = _field_combo("Date of each level (any field type). Optional.")
        self.wl_table_kind_field = _field_combo("Measured or ATD. Optional: without it every row is an ATD level.")
        self.wl_atd_values = QgsCheckableComboBox(self.editor)
        self.wl_atd_values.setDefaultText("(none)")
        self.wl_atd_values.setToolTip("Kind values drawn as ATD levels (filled triangles); the others are measured")
        _narrow(self.wl_atd_values)
        self.table_box = QWidget()
        tb = QVBoxLayout(self.table_box)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(8)
        tb.addWidget(pair(field_box("Exploration name", self.wl_table_name_field),
                          field_box("Water level", self.wl_table_elev_field)))
        tb.addWidget(pair(field_box("Date", self.wl_table_date_field), field_box("Kind", self.wl_table_kind_field)))
        tb.addWidget(field_box("ATD when kind is", self.wl_atd_values))
        self.table_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.table_box.hide()
        lay.addWidget(self.table_box)
        self.water_hint = Hint(NO_WATER_HINT)
        self.water_hint.setWanted(False)
        lay.addWidget(self.water_hint)

    def _connect_editor(self) -> None:
        self.tabs.currentChanged.connect(self._show_pane)
        self.look_seg.currentIndexChanged.connect(self._on_look_edit)
        self.in_range_box.toggled.connect(self._on_header_edit)
        for box in (self.top_field, self.bottom_elev_field, self.depth_field, self.screen_top_field,
                    self.screen_bottom_field, self.wl_field, self.wl_date_field, self.atd_field, self.atd_date_field,
                    self.wl_table_name_field, self.wl_table_elev_field, self.wl_table_date_field):
            box.fieldChanged.connect(self._on_field_edit)
        self.wl_values.currentIndexChanged.connect(self._on_field_edit)
        self.screen_values.currentIndexChanged.connect(self._on_field_edit)
        self.wl_table.layerChanged.connect(self._on_table_combo)
        self.wl_table.activated.connect(self._on_table_combo)
        self.wl_table_kind_field.fieldChanged.connect(self._on_kind_edit)
        self.wl_atd_values.checkedItemsChanged.connect(self._on_atd_edit)
        try:                                   # (checkedItemsChanged may wait for the popup to close)
            self.wl_atd_values.model().itemCheckStateChanged.connect(self._on_atd_edit)
        except (AttributeError, TypeError):    # pragma: no cover
            pass

    def _field_boxes(self):
        return (("label_field", self.label_field, False, False), ("type_field", self.type_field, False, True),
                ("top_field", self.top_field, True, True), ("bottom_elev_field", self.bottom_elev_field, True, True),
                ("depth_field", self.depth_field, True, True),
                ("screen_top_field", self.screen_top_field, True, True),
                ("screen_bottom_field", self.screen_bottom_field, True, True),
                ("wl_field", self.wl_field, True, True), ("wl_date_field", self.wl_date_field, False, True),
                ("atd_field", self.atd_field, True, True), ("atd_date_field", self.atd_date_field, False, True))

    def _table_boxes(self) -> Sequence[Tuple[str, QgsFieldComboBox, bool, bool]]:
        return (("wl_table_name_field", self.wl_table_name_field, False, False),
                ("wl_table_elev_field", self.wl_table_elev_field, True, False),
                ("wl_table_date_field", self.wl_table_date_field, False, True),
                ("wl_table_kind_field", self.wl_table_kind_field, False, True))

    def _guess(self, fields, pk, layer_name, d, guess_fields, text_ok=None):
        return G.guess_point_fields(fields, pk, layer_name, saved=d, guess_fields=guess_fields, text_ok=text_ok)

    # ---- header
    def _header_value(self) -> dict:
        out = super()._header_value()
        out.update(look=self.look_seg.currentData() or "black", in_range=self.in_range_box.isChecked())
        return out

    def _set_header(self, d: dict) -> None:
        super()._set_header(d)
        _set_combo_data(self.look_seg, d["look"])
        self.in_range_box.setChecked(d["in_range"])

    def _on_look_edit(self, *args) -> None:
        """The user chose Black, Gray or Color: the style is read again (it may have changed since)."""
        if self._filling:
            return
        self._style = self._read_style(self.layer())
        self._on_header_edit()

    # ---- tabs (0.3.6)
    def set_editor_open(self, on: bool) -> None:
        """Open or close the editor, its tabs and the guess's hint with it."""
        on = bool(on)
        self.tabs.setVisible(on)
        super().set_editor_open(on)
        self._sync_guess_hint()

    def rule_y(self) -> Optional[int]:
        """The tabs' bottom pixel row (in the card) while open: the section body paints their rule across the band."""
        return self.tabs.geometry().bottom() if self.editor_open() and not self.tabs.isHidden() else None

    def show_tab(self, which: Union[str, int, None] = None) -> None:
        """Open the editor on the tab `which` ("layer" | "depths" | "water", or 0-2; None: the current one) and
        scroll the row into view."""
        if which is not None:
            i = TAB_KEYS.index(which) if isinstance(which, str) else int(which)
            self.tabs.setCurrentIndex(i)
        super().show_tab()

    def current_tab(self) -> str:
        """"layer" | "depths" | "water"."""
        return TAB_KEYS[self.tabs.currentIndex()]

    def _show_pane(self, i: int) -> None:
        for j, pane in enumerate((self.pane_layer, self.pane_depths, self.pane_water)):
            pane.setVisible(j == i)

    # ---- the layer's QGIS style (Color)
    @staticmethod
    def _read_style(layer: Optional[QgsVectorLayer]) -> Optional[LayerStyle]:
        """layer_style(layer), None without a layer; a style that cannot be read has no symbols (drawn black, as the
        build draws it)."""
        if layer is None:
            return None
        try:
            return layer_style(layer)
        except Exception:                      # pragma: no cover - a renderer that cannot be read
            return LayerStyle("none")

    def current_style(self) -> Optional[LayerStyle]:
        """The layer's style as last read (refresh_style). (Not `style`: that is QWidget's.)"""
        return self._style

    def refresh_style(self) -> None:
        """Read the layer's style again (its symbology changed in QGIS, or Refresh), silently."""
        self._style = self._read_style(self.layer())
        self.refresh_labels()

    def set_plotted_styles(self, keys: Optional[Set[str]]) -> None:
        """The style item keys of this row's explorations on the section (the dock, after each build; None before a
        model or on a failed build): their chips come first in the style box."""
        keys = set(keys) if keys is not None else None
        if keys != self._plotted_keys:
            self._plotted_keys = keys
            self.refresh_labels()

    # ---- fields and the table
    def _fields_value(self) -> dict:
        out = super()._fields_value()
        out.update(wl_values=self.wl_values.currentData() or "elevation",
                   screen_values=self.screen_values.currentData() or "depth")
        if not self._table_frozen():
            tbl = self.wl_table.currentLayer()
            out["wl_table_id"] = tbl.id() if tbl is not None else ""
            for key, box, _num, _empty in self._table_boxes():
                out[key] = box.currentField()
            out["wl_atd_values"] = self._atd_values()
        return out

    def _table_frozen(self) -> bool:
        """The table boxes do not hold the row's table: it is gone (they show none; the stored table is written
        back, as 0.3.2 did), the project is removing layers, or they were not filled for it yet."""
        if self._removing:
            return True
        tid = self._stored.get("wl_table_id", "")
        tbl = table_layer(tid)
        if tid and tbl is None:
            return True
        return not (_shows(self.wl_table, tbl) and _shows(self.wl_table_name_field, tbl))

    def _apply_extra(self, d: dict, guess: dict, guess_table: bool) -> None:
        self._style = self._read_style(self._resolve(d["layer_id"]))
        _set_combo_data(self.wl_values, guess.get("wl_values", d["wl_values"]))
        _set_combo_data(self.screen_values, d["screen_values"])
        tbl = table_layer(d["wl_table_id"])
        self.wl_table.setLayer(tbl)
        self._set_table_fields(tbl, dict(d, wl_values=self.wl_values.currentData() or d["wl_values"]),
                               keep_empty=not guess_table)
        self._fill_atd_values(d["wl_atd_values"])

    def _set_table_fields(self, tbl: Optional[QgsVectorLayer], saved: dict, keep_empty: bool) -> None:
        """The table's field boxes for `tbl`: the saved fields it has, else guessed (point_guess.guess_table_fields;
        an empty saved date or kind stays empty with `keep_empty`; the level by `saved`'s "Levels are"). Inside a
        fill (silent)."""
        for _key, box, _num, _empty in self._table_boxes():
            box.setLayer(tbl)
        if tbl is None:
            return
        fields, pk = layer_fields(tbl)
        g = G.guess_table_fields(fields, pk, saved=saved, keep_empty=keep_empty, wl_values=saved.get("wl_values"),
                                 text_ok=number_texts(tbl))
        for key, box, numeric, may_be_empty in self._table_boxes():
            set_field(box, g[key], (), allow_empty=may_be_empty, numeric=numeric, keep_empty=True, pk=pk)

    def uses_layer_ids(self) -> Set[str]:
        return {self._stored.get("layer_id", ""), self._stored.get("wl_table_id", "")} - {""}

    def _needs_sync(self) -> bool:
        if super()._needs_sync():
            return True
        tbl = table_layer(self._stored.get("wl_table_id", ""))
        return not (_shows(self.wl_table, tbl) and _shows(self.wl_table_name_field, tbl))

    def _new_layer_keys(self, d: dict, layer: Optional[QgsVectorLayer]) -> None:
        if layer is not None:
            d["in_range"] = G.guess_in_range(layer.name(), layer.fields().names())

    def reload_values(self) -> None:
        """Refresh: read the type values, the table's kind values (keeping the ticks) and the layer's style again,
        silently."""
        super().reload_values()
        if not self._frozen() and not self._table_frozen():
            self._fill_atd_values(self._atd_values())
        self.refresh_style()

    def _kind_values(self) -> List[str]:
        table, field = self.wl_table.currentLayer(), self.wl_table_kind_field.currentField()
        if not isinstance(table, QgsVectorLayer) or not field:
            return []
        idx = table.fields().lookupField(field)
        if idx < 0:
            return []
        out = set()
        for v in table.uniqueValues(idx, 500):
            text = _type_key(v).strip()
            if text:
                out.add(text)
        return sorted(out, key=str.lower)

    def _fill_atd_values(self, stored: Sequence[str]) -> None:
        """The kind values, checked when drawn as ATD. Nothing stored means the automatic choice: the values
        containing "ATD" (any case), shown checked."""
        combo = self.wl_atd_values
        self._filling += 1
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
            self._filling -= 1

    def _atd_values(self) -> List[str]:
        """wl_atd_values from the checks: [] when they are the automatic choice."""
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
        prev = list(self._stored.get("wl_atd_values") or [])
        if set(checked) == set(prev):
            return prev
        return checked

    def _on_table_combo(self, *args) -> None:
        """The user chose a table of water levels (or none)."""
        if self._filling or self._removing or self._frozen():
            if not self._filling and not self._removing:
                self._filling += 1
                try:                                       # the row's layer is missing: the table stays as stored
                    self.wl_table.setLayer(table_layer(self._stored.get("wl_table_id", "")))
                finally:
                    self._filling -= 1
            return
        tbl = self.wl_table.currentLayer()
        new_id = tbl.id() if tbl is not None else ""
        if new_id == self._stored.get("wl_table_id", "") and not self._table_frozen():
            return
        prev = self.value()                # fields kept where the new table has them, else guessed (as 0.3.2)
        self._filling += 1
        try:
            self._stored["wl_table_id"] = new_id
            self._set_table_fields(tbl, prev, keep_empty=False)
            self._stored["wl_atd_values"] = []
            self._fill_atd_values([])
        finally:
            self._filling -= 1
        self._user_edit()

    def _on_kind_edit(self, *args) -> None:
        if self._filling or self._frozen() or self._table_frozen():
            return
        self._fill_atd_values([])
        self._user_edit()

    def _on_atd_edit(self, *args) -> None:
        if self._filling or self._frozen() or self._table_frozen():
            return
        if self._atd_values() != list(self._stored.get("wl_atd_values") or []):     # (two signals per tick)
            self._user_edit()

    # ---- enabling (the per-row half of the dock's _update_enabled)
    def set_shared(self, depth_line: bool, top_mode: str, screens: bool) -> None:
        """The shared settings that enable this row's boxes: the depth line (bottom, depth; the top unless tops come
        from LIDAR) and screens (every water and screen box)."""
        self._shared = (bool(depth_line), str(top_mode), bool(screens))
        self._sync_enabled()

    def has_bottom_and_depth(self) -> bool:
        d = self.value()
        return bool(d["bottom_elev_field"]) and bool(d["depth_field"])

    def _sync_enabled(self) -> None:
        super()._sync_enabled()
        line, top_mode, on = self._shared
        for w in (self.bottom_elev_field, self.depth_field):
            w.setEnabled(line)
        self.top_field.setEnabled(line and top_mode != "dem")
        for w in (self.screen_top_field, self.screen_bottom_field, self.screen_values, self.wl_values, self.wl_field,
                  self.atd_field, self.wl_table):
            w.setEnabled(on)
        self.wl_date_field.setEnabled(on and bool(self.wl_field.currentField()))
        self.atd_date_field.setEnabled(on and bool(self.atd_field.currentField()))
        tbl = self.wl_table.currentLayer()
        self.table_box.setHidden(tbl is None)
        for _key, box, _num, _empty in self._table_boxes():
            box.setEnabled(on and tbl is not None)
        self.wl_atd_values.setEnabled(on and tbl is not None and bool(self.wl_table_kind_field.currentField()))
        self.range_hint.setWanted(not self.in_range_box.isChecked())

    # ---- labels
    def look_color(self) -> str:
        """The header swatch's (first) colour."""
        return self.swatch.color()

    def _swatch_colors(self, look: str) -> List[str]:
        """Black: BLACK_INK; Gray: LOOK_GRAY; Color: the colours of the first three chips, BLACK_INK without a chip
        (no style, no symbols, a missing layer, every item switched off: those lines are drawn black)."""
        if look == "gray":
            return [LOOK_GRAY]
        if look == "color":
            return [c for _label, c in self.style_box.chips.items()][:3] or [BLACK_INK]
        return [BLACK_INK]

    def subtitle(self, d: Optional[dict] = None) -> str:
        """The header's second line (0.3.6, the mockup's): "label · k of n types · look", then "table <name>" with a
        table of water levels; "layer not in the project · look" for a missing layer; "no layer chosen"."""
        d = d or self.value()
        if self.layer() is None:
            return f"layer not in the project · {d['look']}" if self.is_missing() else "no layer chosen"
        parts = [d["label_field"]] if d["label_field"] else []
        parts += [self._types_part(d), d["look"]]
        tbl = table_layer(d["wl_table_id"])
        if tbl is not None:
            parts.append(f"table {tbl.name()}")
        return " · ".join(parts)

    def refresh_labels(self) -> None:
        d = self.value()
        self._show_name(d)
        look = d["look"]
        lyr = self.layer()
        self.style_box.set_style(self._style, missing=self.is_missing(), plotted=self._plotted_keys)
        self.style_box.setHidden(look != "color")
        self.look_hint.setWanted(look != "color")
        self.swatch.set_colors(self._swatch_colors(look))
        self.sub_label.setText(self.subtitle(d))
        self.sub_label.setKeyPart(d["label_field"] if lyr is not None else "")
        no_water = lyr is not None and not any(d[k] for k in WATER_KEYS)
        self.water_hint.setWanted(no_water)
        self.tabs.setTabDimmed(2, no_water, NO_WATER_TIP)
        self.range_hint.setWanted(not d["in_range"])
        self.guess_hint.setText(G.guess_hint(d, self._guessed, d["wl_values"]) if lyr is not None else "")
        self._sync_guess_hint()
        self._sync_check(d)

    def _sync_guess_hint(self) -> None:
        """The guess's sentence over the tabs: while the row is open and it has guesses he has not checked."""
        self.guess_hint.setWanted(bool(self.guess_hint.text()) and self.editor_open())

    # ---- guesses (0.3.6, D14, D15)
    def _guess_card(self, d: dict) -> Optional[CardInfo]:
        """"Fields were guessed": each guessed box and its field (a level's or screen's kind after it), a button to
        the tab of the first one not on the Layer tab, and "Looks right"."""
        if not self._guessed or self.layer() is None:
            return None
        items = [(FIELD_TERMS[k], d[k], self._guess_suffix(k, d)) for k in self._guessed]
        rest = [k for k in self._guessed if k not in LAYER_KEYS]       # on the Depths or Water tab
        if not rest:
            tab = ("open_layer", "Open Layer")
        elif rest[0] in DEPTH_KEYS:
            tab = ("open_depths", "Open Depths")
        else:
            tab = ("open_water", "Open Water")
        return CardInfo(GUESS_TITLE, source=f"{self.name_label.text()} · from the field names", items=items,
                        mono=True, actions=[tab, ("looks_right", "Looks right")])

    @staticmethod
    def _guess_suffix(key: str, d: dict) -> str:
        if key in ("wl_field", "atd_field"):
            return " · depths" if d["wl_values"] == "depth" else " · elevations"
        if key in ("screen_top_field", "screen_bottom_field"):
            return " · depths" if d["screen_values"] == "depth" else " · elevations"
        return ""

    def _drop_checked(self) -> None:
        super()._drop_checked()
        if self._guessed and (self.wl_values.currentData() or "elevation") != self._stored.get("wl_values"):
            self._guessed = [k for k in self._guessed if k not in ("wl_field", "atd_field")]   # his Levels are


# ---------------------------------------------------------------- the symbol drop-down (0.3.6)
@lru_cache(maxsize=None)
def _list_icon(key: str) -> QIcon:
    """A symbol's picture in the drop-down's list: in its usual colour on the white chip (made once per process)."""
    return symbol_icon(key, None, 22, 16, background="#ffffff")


@lru_cache(maxsize=256)
def _box_icon(key: str, color: str) -> QIcon:
    """The closed drop-down's picture: the row's symbol in the row's colour."""
    return symbol_icon(key, color, 20, 14, background="#ffffff")


class _SymbolDelegate(QStyledItemDelegate):
    """The drop-down's rows (the mockup's sympop): a group header in small muted capitals (22 px), a symbol as its
    22 x 16 picture and its name (24 px); hovered, the hover colour; the box's current symbol on the bar colour."""

    HEADER_H, ITEM_H = 22, 24

    def __init__(self, combo: "SymbolCombo"):
        super().__init__(combo)
        self._combo = combo

    def sizeHint(self, option, index) -> QSize:
        return QSize(max(option.rect.width(), 1), self.HEADER_H if index.data(HEADER_ROLE) else self.ITEM_H)

    def paint(self, p, option, index) -> None:
        t = theme_for(self._combo.palette())
        r = QRect(option.rect)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        base = self._combo.font()
        p.save()
        if index.data(HEADER_ROLE):
            p.setFont(_px_font(base, 9.5, QFont.Weight.Bold, 7.0))
            p.setPen(t.muted)
            p.drawText(r.adjusted(9, 6, -9, -2), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom),
                       text.upper())
        else:
            current = index.row() == self._combo.currentIndex()
            if current:
                p.fillRect(r, t.bar)
            elif option.state & (QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected):
                p.fillRect(r, t.hover)
            icon = index.data(Qt.ItemDataRole.DecorationRole)
            if isinstance(icon, QIcon):
                icon.paint(p, QRect(r.x() + 9, r.y() + (r.height() - 16) // 2, 22, 16))
            font = _px_font(base, 11.5)
            p.setFont(font)
            p.setPen(t.on_bar if current else t.ink)
            tr = r.adjusted(9 + 22 + 7, 0, -9, 0)
            p.drawText(tr, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, tr.width()))
        p.restore()


class SymbolCombo(QComboBox):
    """The symbol drop-down of a point or line row (0.3.6, D7; the mockup's sympop): the catalogue of render.symbols
    in its five groups (symbols.grouped(): a header per group, never selectable or current; then each symbol, its
    picture in its usual colour and its name, its description as its tooltip). A legacy key the row holds (the star)
    is listed last, under "Kept from an older version", while the row holds it. The closed box shows the row's symbol
    in the row's colour. set_symbol is silent; symbolChosen(key) is a user's pick."""

    symbolChosen = pyqtSignal(str)
    ICON = QSize(20, 14)                   # the closed box's picture
    _CLICKS = (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._color = usual_color(OTHER_POINT_DEFAULTS["shape"])
        self._legacy = ""
        # a list under the box with a scroll bar, its first header in sight (the mockup's), not a menu over the box
        # (Fusion's): a style property only, the box is drawn as before (set before the view: with a menu popup the
        # view gets no scroll bar)
        self.setStyleSheet("QComboBox { combobox-popup: 0; }")
        view = QListView(self)
        view.setObjectName("xsSymbolList")
        view.setMinimumWidth(262)
        view.setUniformItemSizes(False)
        self.setView(view)
        # a click on a group header picks nothing: Qt's popup picks the view's current item on any release in the
        # list, which under Fusion is the item hovered last (headers never become current). Installed after setView,
        # this filter runs before the popup's own.
        view.viewport().installEventFilter(self)
        self.setItemDelegate(_SymbolDelegate(self))
        self.setMaxVisibleItems(13)
        model = QStandardItemModel(self)
        for group, items in grouped():
            model.appendRow(self._header(group))
            for s in items:
                model.appendRow(self._item(s.key))
        self.setModel(model)
        self.setIconSize(self.ICON)
        _narrow(self)
        self.activated.connect(self._on_activated)
        self.set_symbol(OTHER_POINT_DEFAULTS["shape"], self._color)

    @staticmethod
    def _header(text: str) -> QStandardItem:
        it = QStandardItem(text)
        it.setFlags(Qt.ItemFlag.NoItemFlags)
        it.setData(True, HEADER_ROLE)
        return it

    @staticmethod
    def _item(key: str) -> QStandardItem:
        it = QStandardItem(SYMBOLS[key].name)
        it.setData(key, Qt.ItemDataRole.UserRole)
        it.setData(_list_icon(key), Qt.ItemDataRole.DecorationRole)
        it.setToolTip(SYMBOL_TIPS.get(key, LEGACY_TIP))
        it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        return it

    def _set_legacy(self, key: str) -> None:
        """List the legacy `key` last ("" none)."""
        if key == self._legacy:
            return
        m = self.model()
        if self._legacy:
            m.removeRows(m.rowCount() - 2, 2)
        self._legacy = key
        if key:
            m.appendRow(self._header(LEGACY_HEADER))
            m.appendRow(self._item(key))

    def set_symbol(self, key: str, color: Optional[str] = None) -> None:
        """Show the symbol `key` (silently) and, in the closed box, in `color`."""
        self.blockSignals(True)
        try:
            self._set_legacy(key if key in LEGACY_KEYS else "")
            i = self.findData(key)
            if i >= 0 and i != self.currentIndex():
                self.setCurrentIndex(i)
        finally:
            self.blockSignals(False)
        if color and QColor(color).isValid():
            self._color = QColor(color).name()
        self.update()

    def current_key(self) -> str:
        return str(self.currentData() or "")

    def color(self) -> str:
        return self._color

    def _on_activated(self, i: int) -> None:
        key = self.itemData(i)
        if key:
            self.symbolChosen.emit(str(key))

    def eventFilter(self, obj, e) -> bool:
        """The list's clicks on a group header (or on no item) are eaten: the popup stays open, nothing is picked."""
        if e.type() in self._CLICKS and obj is self.view().viewport():
            index = self.view().indexAt(e.position().toPoint())
            if not index.isValid() or index.data(HEADER_ROLE) or not (index.flags() & Qt.ItemFlag.ItemIsEnabled):
                return True
        return super().eventFilter(obj, e)

    def paintEvent(self, _e) -> None:
        p = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        key = self.current_key()
        if key:
            opt.currentIcon = _box_icon(key, self._color)
            opt.iconSize = self.ICON
        p.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)
        p.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, opt)


# ---------------------------------------------------------------- an Other features row
class OtherPointsRow(_PointRow):
    """One layer of other features (0.3.6, D7: points, lines or polygons): [visible] [symbol or bracket] [name /
    "points · label · where" | "lines · label · N crossings" | "areas · label · bracket in the frame"] [⋯] over its
    editor: layer, legend name and label, type field and types, then by its layer's kind: for points and lines the
    symbol (the grouped drop-down; choosing one sets its usual color), colour and size and where each point or crossing
    sits (the ground line, the LIDAR at the point, or a field, with what to do where it is empty; a line row: Ground
    line | Field); for polygons the bracket (in the frame or above it), its edge lines, colour and line style. The
    row's `kind` follows its layer (the stored one while the layer is missing). (Class name of 0.3.3.)"""

    DEFAULTS = OTHER_POINT_DEFAULTS
    ROW_TIP = ROW_TIPS["point"]
    LAYER_FILTERS = Qgis.LayerFilter.PointLayer | Qgis.LayerFilter.LineLayer | Qgis.LayerFilter.PolygonLayer
    EMPTY_TEXT = EMPTY_FEATURE_LAYER
    _kind = "point"                        # FEATURE_KINDS: its layer's, else the row's (_resolved)

    def _make_swatch(self) -> QWidget:
        sw = SymbolSwatch(OTHER_POINT_DEFAULTS["shape"], OTHER_POINT_DEFAULTS["color"])
        sw.setToolTip(SWATCH_TIPS["point"])
        return sw

    def _clean(self, d: dict) -> dict:
        return clean_other_point(d) or copy.deepcopy(OTHER_POINT_DEFAULTS)

    def _resolve(self, layer_id: str) -> Optional[QgsVectorLayer]:
        return feature_layer(layer_id)

    def _make_type_field(self) -> QgsFieldComboBox:
        c = FieldComboWithNone("(none: every feature)")
        c.setToolTip("Field of the types to plot (none: every feature)")
        _narrow(c)
        return c

    def _build_editor(self, ed: QVBoxLayout) -> None:
        ed.addWidget(field_box("Layer", self.layer_combo))
        ed.addWidget(pair(field_box("Legend", self.name_edit), field_box("Label", self.label_field)))
        ed.addWidget(field_box("Type", self.type_field))
        self.types_box = field_box("Types", self.type_box, links=[self.btn_types_all, self._types_dot,
                                                                  self.btn_types_none])
        ed.addWidget(self.types_box)
        # the symbol, its colour and size (points and lines; the mockup's g3: the drop-down, 30 px, 64 px)
        self.symbol_combo = SymbolCombo(self.editor)
        self.symbol_combo.setToolTip("The symbol drawn for each feature (choosing one sets its usual color)")
        self.color_btn = QgsColorButton(self.editor)
        self.color_btn.setShowMenu(False)
        self.color_btn.setAllowOpacity(False)
        self.color_btn.setColorDialogTitle("Symbol color")
        self.color_btn.setFixedSize(30, 24)
        self.color_btn.setToolTip(COLOR_TIPS["point"])
        self.size_spin = _spin(OTHER_SIZE_MIN, OTHER_SIZE_MAX, 1, 0.5, " pt")
        self.size_spin.setToolTip("Size of the symbol, points")
        self.color_box = field_box("Color", self.color_btn)          # in the symbol row, or a polygon's style row
        size_box = field_box("Size", self.size_spin)
        for box, w in ((self.color_box, 30), (size_box, 64)):        # (Fixed: an Ignored box gets no room)
            box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            box.setFixedWidth(w)
        self.symbol_row = QWidget()
        sl = QHBoxLayout(self.symbol_row)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        sl.addWidget(field_box("Symbol", self.symbol_combo), 1, Qt.AlignmentFlag.AlignBottom)
        sl.addWidget(self.color_box, 0, Qt.AlignmentFlag.AlignBottom)
        sl.addWidget(size_box, 0, Qt.AlignmentFlag.AlignBottom)
        self.symbol_row.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        ed.addWidget(self.symbol_row)
        # where each point or crossing sits (points and lines)
        self.elev_seg = _segmented(ELEV_CHOICES, ELEV_TIPS)
        self.elev_box = field_box("Elevation", self.elev_seg)
        ed.addWidget(self.elev_box)
        self.elev_field = _numeric_field_combo("Elevation of each point, ft")
        self.empty_seg = _segmented(EMPTY_CHOICES, EMPTY_TIPS)
        self.elev_field_row = pair(field_box("Field", self.elev_field), field_box("Where empty", self.empty_seg))
        self.elev_field_row.hide()
        ed.addWidget(self.elev_field_row)
        # the bracket (polygons)
        self.bracket_seg = _segmented(BRACKET_CHOICES, BRACKET_TIPS)
        self.bracket_box = field_box("Bracket", self.bracket_seg)
        ed.addWidget(self.bracket_box)
        self.edges_seg = _segmented(EDGE_CHOICES, EDGE_TIPS)
        self.edges_box = field_box("Edge lines", self.edges_seg)
        ed.addWidget(self.edges_box)
        self.bracket_style_seg = _segmented(BRACKET_STYLE_CHOICES, BRACKET_STYLE_TIPS)
        self.area_style_row = QWidget()
        al = QHBoxLayout(self.area_style_row)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        al.addWidget(field_box("Line", self.bracket_style_seg), 1, Qt.AlignmentFlag.AlignBottom)
        self.area_style_row.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        ed.addWidget(self.area_style_row)
        for w in (self.bracket_box, self.edges_box, self.area_style_row):
            w.hide()
        self.elev_hint = Hint("")
        ed.addWidget(self.elev_hint)

    def _connect_editor(self) -> None:
        for seg in (self.elev_seg, self.empty_seg, self.bracket_seg, self.edges_seg, self.bracket_style_seg):
            seg.currentIndexChanged.connect(self._on_header_edit)
        self.symbol_combo.symbolChosen.connect(self._on_symbol_chosen)
        self.color_btn.colorChanged.connect(self._on_header_edit)
        self.size_spin.valueChanged.connect(self._on_header_edit)
        self.elev_field.fieldChanged.connect(self._on_field_edit)

    def _field_boxes(self):
        return (("label_field", self.label_field, False, False), ("type_field", self.type_field, False, True),
                ("elev_field", self.elev_field, True, True))

    def _guess(self, fields, pk, layer_name, d, guess_fields, text_ok=None):
        return G.guess_other_row(fields, pk, layer_name, saved=d, guess_fields=guess_fields, text_ok=text_ok), "", []

    # ---- the kind (0.3.6)
    def kind(self) -> str:
        """"point" | "line" | "polygon": its layer's geometry, the stored kind while the layer is missing."""
        return self._kind

    def _resolved(self, d: dict, layer: Optional[QgsVectorLayer]) -> None:
        self._kind = (feature_kind(layer) if layer is not None else "") or d["kind"]
        self._set_kind(self._kind, d)

    def _set_kind(self, kind: str, d: dict) -> None:
        """Show the editor of `kind`: the symbol and elevation of points and lines (a line row's LIDAR buttons only
        when `d` has them), or the bracket of polygons; the colour box moves into the kind's row."""
        area = kind == "polygon"
        for w in (self.symbol_row, self.elev_box):
            w.setHidden(area)
        for w in (self.bracket_box, self.edges_box, self.area_style_row):
            w.setHidden(not area)
        if area:
            self.elev_field_row.hide()
        old, new = (self.symbol_row, self.area_style_row) if area else (self.area_style_row, self.symbol_row)
        if old.layout().indexOf(self.color_box) >= 0:
            old.layout().removeWidget(self.color_box)
            new.layout().insertWidget(0 if area else 1, self.color_box, 0, Qt.AlignmentFlag.AlignBottom)
        line = kind == "line"
        self.elev_seg.buttons()[1].setHidden(line and d["elev"] != "lidar")
        self.empty_seg.buttons()[1].setHidden(line and d["elev_empty"] != "lidar")
        self.visible_box.setToolTip(ROW_TIPS.get(kind, self.ROW_TIP))
        self.swatch.setToolTip(SWATCH_TIPS.get(kind, ""))
        self.color_btn.setToolTip(COLOR_TIPS.get(kind, ""))

    def _new_layer_keys(self, d: dict, layer: Optional[QgsVectorLayer]) -> None:
        """A user's layer of another kind: the row takes its kind, and an untouched symbol and colour become the new
        kind's defaults (model.DEFAULT_SHAPE, the symbol's usual colour; a polygon row's AREA_COLOR_DEFAULT)."""
        new = feature_kind(layer) if layer is not None else ""
        old = d["kind"]
        if not new or new == old:
            return
        old_color = AREA_COLOR_DEFAULT if old == "polygon" else usual_color(d["shape"])
        d["kind"] = new
        if d["shape"] == DEFAULT_SHAPE[old]:
            d["shape"] = DEFAULT_SHAPE[new]
        if str(d["color"]).lower() == old_color.lower():
            d["color"] = AREA_COLOR_DEFAULT if new == "polygon" else usual_color(d["shape"])

    # ---- header
    def _header_value(self) -> dict:
        out = super()._header_value()
        size = float(self.size_spin.value())
        stored = float(self._stored.get("size", size))
        if abs(stored - size) <= 0.5 * 10.0 ** -self.size_spin.decimals() + 1e-9:
            size = stored                  # the box shows a stored 7.25 as 7.3: keep what was stored
        out.update(shape=self.symbol_combo.current_key() or self._stored.get("shape", "asterisk"),
                   color=self.color_btn.color().name(), size=size, elev=self.elev_seg.currentData() or "line",
                   elev_empty=self.empty_seg.currentData() or "line", kind=self._kind,
                   bracket=self.bracket_seg.currentData() or "inside",
                   bracket_style=self.bracket_style_seg.currentData() or "solid",
                   edges=self.edges_seg.currentData() or "off")
        return out

    def _set_header(self, d: dict) -> None:
        super()._set_header(d)
        self.symbol_combo.set_symbol(d["shape"], d["color"])
        self.color_btn.setColor(QColor(d["color"]))
        self.size_spin.setValue(d["size"])
        _set_combo_data(self.elev_seg, d["elev"])
        _set_combo_data(self.empty_seg, d["elev_empty"])
        _set_combo_data(self.bracket_seg, d["bracket"])
        _set_combo_data(self.bracket_style_seg, d["bracket_style"])
        _set_combo_data(self.edges_seg, d["edges"])

    def _on_symbol_chosen(self, key: str) -> None:
        """His pick in the drop-down: the symbol and its usual colour (D7; he can change the colour after)."""
        if self._filling:
            return
        self._filling += 1
        try:
            self.color_btn.setColor(QColor(usual_color(key)))
        finally:
            self._filling -= 1
        self._on_header_edit()

    def set_shared(self, *args, **kw) -> None:
        """Nothing shared enables an Other features box (kept so the dock can treat both kinds alike)."""

    def _sync_enabled(self) -> None:
        super()._sync_enabled()
        self.types_box.setHidden(not self.type_field.currentField())
        self.elev_field_row.setHidden(self._kind == "polygon" or self.elev_seg.currentData() != "field")

    # ---- labels
    def how_text(self, d: Optional[dict] = None) -> str:
        """Where the points sit, as the readout says it."""
        d = d or self.value()
        if d["elev"] == "line":
            return "on the ground line"
        if d["elev"] == "lidar":
            return "LIDAR at the point"
        field = d["elev_field"] or "(no field)"
        return field + {"line": ", else on the ground line", "lidar": ", else LIDAR", "off": " only"}[d["elev_empty"]]

    def hint_text(self, d: Optional[dict] = None) -> str:
        """The Verbose hint under the editor, by the kind (points: where they sit)."""
        d = d or self.value()
        if self._kind == "line":
            return LINE_HINT
        if self._kind == "polygon":
            return AREA_HINT
        a, b = self._ends
        if d["elev"] == "line":
            return (f"Each point sits on the ground line drawn along {a}–{b}, just touching it. Choose LIDAR or a field "
                    "to show its own elevation.")
        if d["elev"] == "lidar":
            return (f"The LIDAR at each point's own location, which can differ from the ground line drawn along "
                    f"{a}–{b}. The centre of the symbol marks the elevation.")
        then = {"line": "sits on the ground line", "lidar": "uses the LIDAR at the point",
                "off": "is left out"}[d["elev_empty"]]
        return (f"The centre of the symbol marks the elevation. Where {d['elev_field'] or 'the field'} is empty, the "
                f"point {then}.")

    def subtitle(self, d: Optional[dict] = None) -> str:
        """The header's second line (0.3.6, D7): "points · label · ground line | LIDAR | <field>", "lines · label ·
        N crossings" (once a model counted them), "areas · label · bracket in | above the frame"; "<kind> · layer not
        in the project"; "no layer chosen". No label field: no label part."""
        d = d or self.value()
        word = KIND_WORDS.get(self._kind, "points")
        if self.layer() is None:
            return f"{word} · layer not in the project" if self.is_missing() else "no layer chosen"
        parts = [word] + ([d["label_field"]] if d["label_field"] else [])
        if self._kind == "line":
            if self._counts is not None:
                n = sum(self._counts[0].values())
                parts.append(f"{n} crossing{'s' if n != 1 else ''}")
        elif self._kind == "polygon":
            parts.append("bracket above the frame" if d["bracket"] == "above" else "bracket in the frame")
        else:
            parts.append({"line": "ground line", "lidar": "LIDAR"}.get(d["elev"]) or d["elev_field"] or "(no field)")
        return " · ".join(parts)

    def refresh_labels(self) -> None:
        d = self.value()
        self._show_name(d)
        if self._kind == "polygon":
            self.swatch.set_bracket(d["color"], d["bracket_style"])
        else:
            self.swatch.set_symbol(d["shape"], d["color"])
        self.symbol_combo.set_symbol(d["shape"], d["color"])
        self.sub_label.setText(self.subtitle(d))
        self.sub_label.setKeyPart(d["label_field"] if self.layer() is not None else "")
        self.elev_hint.setText(self.hint_text(d))
        self.elev_field_row.setHidden(self._kind == "polygon" or d["elev"] != "field")
        self.types_box.setHidden(not d["type_field"])
        self._sync_check(d)
