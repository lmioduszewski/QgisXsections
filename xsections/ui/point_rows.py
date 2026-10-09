"""The point-layer rows of the panel (0.3.3, DESIGN.md decision 22).

- TypeList: the ticked type values of a row's type field, with "plotted / in the layer" counts and a "(no value)"
  row for the NULL-or-empty value.
- PlottedList: "Plotted explorations (N of M, K left off by you)": every exploration the rows choose on this section,
  grouped by row; unticking one leaves it off this section line (the dock keeps the list, Settings.hidden_points).
- PointRowList: the list of rows of the Explorations and Other points sections (moves, removes, renumbering).
- ExplorationRow: one explorations layer (own explorations, explorations by others, supply wells...): its layer,
  legend name, look (Drawn in: Black, Gray or Color), fields, types, "In elevation range" (next to Total depth,
  0.3.5), water fields and its table of water levels. For Color (0.3.4) its LayerStyleBox shows what XSections reads
  from the layer's own QGIS style
  (core.symbology.layer_style): the kind of style, up to four colour chips (those plotted on the section first) and
  how many are switched off.
- OtherPointsRow: one layer of other points (seeps, springs...): its symbol, label and elevation rule.

A row never loses what it was given: it keeps the cleaned dict of its last set_value (`_stored`, updated after each
edit), and while its layer is missing (removed, a moved file, an offline drive) it writes that dict back with only
its header widgets applied, instead of the empty field boxes. Everything the rows do in code is silent: `changed`
is emitted only for a user's edit.

Imports: qgis, core.model, core.symbology (the layer's style, read only), core.explorations (text_number),
render.scales (pure geometry and text), ui.point_guess and ui.widgets; never ui.dock.
"""
from __future__ import annotations

import copy
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from qgis.core import Qgis, QgsFeatureRequest, QgsProject, QgsVectorLayer
from qgis.gui import QgsCheckableComboBox, QgsColorButton, QgsFieldComboBox, QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QPalette
from qgis.PyQt.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QSizePolicy,
                                 QStyle, QStyleOptionComboBox, QStylePainter, QToolButton, QTreeWidget,
                                 QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core.explorations import text_number
from ..core.model import (LOOK_GRAY, NO_ATD, NO_TYPES, OTHER_POINT_DEFAULTS, OTHER_SIZE_MAX, OTHER_SIZE_MIN,
                          POINT_LAYER_DEFAULTS, LayerStyle, Settings, clean_other_point, clean_point_layer)
from ..core.symbology import layer_style
from ..render.scales import pretty_label
from . import point_guess as G
from .widgets import (ClickableArea, Disclosure, ElidedLabel, ExploSwatch, StyleChips, SymbolSwatch, _esc,
                      _field_combo, _narrow, _note, _numeric_field_combo, _segmented, _set_combo_data, _spin,
                      field_box, field_kind, field_label, link_button, pair, set_field, theme_for)

EMPTY_LAYER = "(choose a point layer)"
NO_VALUE_TEXT = "(no value)"           # the NULL-or-empty type value ("" in Settings types)
BLACK_INK = "#111111"                  # the Black look's swatch
SCAN_LIMIT = 200_000                   # a type list counts the values of layers up to this size (else values only)
TEXT_SAMPLE = 50                       # a text field holds numbers when one of its first 50 values (not empty) ...
TEXT_ROWS = 2_000                      # ... in its first 2,000 rows is a number (number_texts, 0.3.5)
PLOTTED_MAX_H = 210                    # px, the Plotted explorations list

# the shapes of the Other points symbol buttons (the mockup's 12 x 12 icons)
_SHAPE_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12">{}</svg>'
SHAPE_ICONS = {
    "asterisk": '<path d="M1 6h10M6 1v10M2.5 2.5l7 7M9.5 2.5l-7 7" stroke="currentColor" stroke-width="1.7" '
                'stroke-linecap="round" fill="none"/>',
    "circle": '<circle cx="6" cy="6" r="4.2" fill="currentColor"/>',
    "square": '<rect x="2" y="2" width="8" height="8" fill="currentColor"/>',
    "diamond": '<path d="M6 1l5 5-5 5-5-5z" fill="currentColor"/>',
    "star": '<path d="M6 .8l1.5 3.4 3.7.3-2.8 2.4.9 3.6L6 8.6 2.7 10.5l.9-3.6L.8 4.5l3.7-.3z" fill="currentColor"/>',
    "triangle": '<path d="M6 1.5l4.5 8.5h-9z" fill="currentColor"/>',
}
SHAPE_CHOICES = [("Asterisk (8 prongs)", "asterisk"), ("Circle", "circle"), ("Square", "square"),
                 ("Diamond", "diamond"), ("Star", "star"), ("Triangle", "triangle")]
ELEV_CHOICES = [("Ground line", "line"), ("LIDAR at point", "lidar"), ("From a field", "field")]
EMPTY_CHOICES = [("Line", "line"), ("LIDAR", "lidar"), ("Off", "off")]
EMPTY_TIPS = ["On the ground line", "LIDAR at the point", "Leave the point off"]
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
    for NULL or empty), column 1 "plotted / in the layer" (or the total before a model). Filling is silent: `changed`
    comes only from a user's tick (an item whose check state differs from its last known one)."""

    changed = pyqtSignal()
    MAX_ROWS = 6
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


# ---------------------------------------------------------------- Plotted explorations
Entry = Tuple[str, int, str, str, bool]          # (layer id, fid, label, detail, plotted)


class PlottedList(Disclosure):
    """"Plotted explorations (N of M, K left off by you)": every exploration the rows choose on this section,
    grouped by row (a bold muted title), each with a tick, its label and "station · offset side". Unticking one emits
    toggled(layer id, fid, False); the dock keeps the list. Filling (set_entries, on every refresh) is silent."""

    toggled = pyqtSignal(str, int, bool)        # a user's tick: (layer id, fid, plotted)
    showAllRequested = pyqtSignal()
    expandedChanged = pyqtSignal(bool)          # the disclosure opened or folded
    TITLE = "Plotted explorations"
    KEY = Qt.ItemDataRole.UserRole              # (layer id, fid) of an exploration item; None for a group title
    STATE = Qt.ItemDataRole.UserRole + 1        # the check state last known

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(self.TITLE, parent)
        self._filling = 0
        self._counts: Optional[Tuple[int, int]] = None      # (plotted, chosen); None: no model
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        self.hint = _note("Untick one to leave it off this section.")
        self.btn_show_all = link_button("Show all", "Plot every exploration you left off on this section")
        hl.addWidget(self.hint, 1)
        hl.addWidget(self.btn_show_all, 0, Qt.AlignmentFlag.AlignTop)
        head.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.addWidget(head)
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
        self.addWidget(self.tree)
        self.empty_label = _note("Nothing chosen yet.")
        self.addWidget(self.empty_label)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.btn_show_all.clicked.connect(self.showAllRequested.emit)
        self.set_entries(None)

    def _on_toggled(self, on: bool) -> None:           # Disclosure's own signal is `toggled`: this list's is a tick
        self.body.setVisible(on)
        self.expandedChanged.emit(on)

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
        if self._counts is None:
            self.setText(self.TITLE)
            return
        n, m = self._counts
        k = m - n
        self.setText(f"{self.TITLE} ({n} of {m}, {k} left off by you)" if k else f"{self.TITLE} ({n} of {m})")

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
    """The rows of the Explorations (or Other points) section, in panel order, made by `factory` (ExplorationRow or
    OtherPointsRow). `changed`: a row's user edit, a move or a remove (never set_rows or append); `rowsChanged`: rows
    added, moved or removed; `emptied`: the user removed the last row. The rows' ⋯ menus are wired here."""

    changed = pyqtSignal()
    rowsChanged = pyqtSignal()
    emptied = pyqtSignal()

    def __init__(self, factory: Callable[[], QWidget], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsPointList")
        self._factory = factory
        self._rows: List[Any] = []
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(1, 1, 1, 1)
        self._lay.setSpacing(0)
        self.setHidden(True)

    @property
    def rows(self) -> List[Any]:
        return list(self._rows)

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
        self._rows.append(row)
        self._lay.addWidget(row)
        return row

    def _drop(self, row) -> None:
        self._lay.removeWidget(row)
        row.setParent(None)
        row.deleteLater()

    def _renumber(self) -> None:
        n = len(self._rows)
        for i, row in enumerate(self._rows):
            row.set_position(i, n)
        if n == 0 or self.parentWidget() is not None:      # (never shown as a window of its own)
            self.setHidden(n == 0)


# ---------------------------------------------------------------- one row (shared by both kinds)
class _PointRow(QFrame):
    """[visible] [swatch] [name / subtitle] [⋯] and, under it, an editor that opens when the name is clicked.
    Subclasses add their own editor fields and say which keys the header holds (_header_value) and which depend on
    the layer's fields (_fields_value)."""

    changed = pyqtSignal()
    moveRequested = pyqtSignal(int)          # -1 up, +1 down
    removeRequested = pyqtSignal()
    layerSwapped = pyqtSignal(str, str, str)  # a user's layer choice: (old layer id, new layer id, old layer's name)
    DEFAULTS: Dict[str, Any] = {}
    ROW_TIP = "Draw this layer"

    def __init__(self, data: Optional[dict] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsPointRow")
        self.setProperty("first", False)
        self._filling = 0
        self._removing = False             # the project is removing layers: the boxes' moves are not choices
        self._stored: dict = self._clean({})
        self._last_name = ""               # the name the row's layer had while it was in the project
        self._hint = ""                    # "Guessed from the field names ..." of this session
        self._counts: Optional[Tuple[Counter, int]] = None
        self._ends = (pretty_label("A"), pretty_label("A'"))

        line = QWidget(self)
        ll = QHBoxLayout(line)
        ll.setContentsMargins(6, 4, 6, 4)
        ll.setSpacing(6)
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
        self.name_label.setBold(True)
        self.sub_label = ElidedLabel("", small=True, parent=self.name_area)
        na.addWidget(self.name_label)
        na.addWidget(self.sub_label)
        self.name_area.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.menu_btn = QToolButton(line)
        self.menu_btn.setObjectName("xsRowMenu")
        self.menu_btn.setText("⋯")
        self.menu_btn.setToolTip("Move up, move down, remove")
        self.menu_btn.setFixedSize(24, 22)
        self.menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.menu_btn)
        self.act_up = menu.addAction("Move up")
        self.act_down = menu.addAction("Move down")
        menu.addSeparator()
        self.act_remove = menu.addAction("Remove")
        self.menu_btn.setMenu(menu)
        ll.addWidget(self.visible_box, 0)
        ll.addWidget(self.swatch, 0)
        ll.addWidget(self.name_area, 1)
        ll.addWidget(self.menu_btn, 0)

        self.editor = QFrame(self)
        self.editor.setObjectName("xsSurfaceEditor")
        ed = QVBoxLayout(self.editor)
        ed.setContentsMargins(28, 7, 8, 9)
        ed.setSpacing(7)
        self.layer_combo = QgsMapLayerComboBox(self.editor)
        self.layer_combo.setFilters(Qgis.LayerFilter.PointLayer)
        self.layer_combo.setAllowEmptyLayer(True, EMPTY_LAYER)
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
        self._build_editor(ed)
        self.editor.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(line)
        lay.addWidget(self.editor)

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

    def _field_boxes(self) -> Sequence[Tuple[str, QgsFieldComboBox, bool, bool]]:
        """(key, box, numbers only, may be empty) of the layer's field boxes."""
        raise NotImplementedError

    def _guess(self, fields, pk, layer_name: str, d: dict, guess_fields: bool, text_ok=None) -> Tuple[dict, str]:
        raise NotImplementedError

    def _header_value(self) -> dict:
        return dict(visible=self.visible_box.isChecked(), name=self.name_edit.text().strip())

    def _set_header(self, d: dict) -> None:
        self.visible_box.setChecked(d["visible"])
        self.name_edit.setText(d["name"])

    def _fields_value(self) -> dict:
        out = {key: box.currentField() for key, box, _num, _empty in self._field_boxes()}
        out["types"] = self.type_list.checked_types() if out.get("type_field") else []
        return out

    def _apply_extra(self, d: dict, guess: dict, guess_table: bool) -> None:
        """Show the subclass's other keys of `d` (inside set_value, silently)."""

    def _new_layer_keys(self, d: dict, layer: Optional[QgsVectorLayer]) -> None:
        """Keys a user's new layer re-guesses (in place)."""

    def _sync_enabled(self) -> None:
        on = bool(self.type_field.currentField())
        for w in (self.type_list, self.btn_types_all, self.btn_types_none):
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
        lyr = point_layer(d["layer_id"])
        prev_id = self._stored.get("layer_id", "")
        self._filling += 1
        try:
            self._stored = copy.deepcopy(d)
            self.layer_combo.setLayer(lyr)
            self._set_header(d)
            for _key, box, _num, _empty in self._field_boxes():
                box.setLayer(lyr)
            guess: dict = {}
            hint = ""
            if lyr is not None:
                fields, pk = layer_fields(lyr)
                guess, hint = self._guess(fields, pk, lyr.name(), d, guess_fields, text_ok=number_texts(lyr))
                for key, box, numeric, may_be_empty in self._field_boxes():
                    set_field(box, guess.get(key, ""), (), allow_empty=may_be_empty, numeric=numeric,
                              keep_empty=True, pk=pk)
                self.type_list.fill(lyr, self.type_field.currentField(), d["types"])
            else:
                self.type_list.fill(None, "", d["types"])
            self._apply_extra(d, guess, guess_table)
            if hint:
                self._hint = hint
            elif d["layer_id"] != prev_id:
                self._hint = ""
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
        return point_layer(self._stored.get("layer_id", ""))

    def is_missing(self) -> bool:
        """A layer was chosen and it no longer resolves to a valid point layer of the project."""
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

    # ---- editor
    def editor_open(self) -> bool:
        return not self.editor.isHidden()

    def set_editor_open(self, on: bool) -> None:
        self.editor.setVisible(bool(on))

    def toggle_editor(self) -> None:
        self.set_editor_open(not self.editor_open())

    def set_position(self, index: int, count: int) -> None:
        self.act_up.setEnabled(index > 0)
        self.act_down.setEnabled(index < count - 1)
        first = index == 0
        if self.property("first") != first:
            self.setProperty("first", first)
            self.style().unpolish(self)
            self.style().polish(self)

    def set_end_labels(self, a: str, b: str) -> None:
        """The section's end labels (with primes) for the row's hints."""
        self._ends = (a or "", b or "")
        self.refresh_labels()

    def set_counts(self, plotted: Optional[Counter], left_off: int = 0) -> None:
        """The model's counts for this row (Counter by type value of its plotted points; None before a model or on a
        failed build), silently."""
        self._counts = (Counter(plotted), int(left_off)) if plotted is not None else None
        self.type_list.set_plotted(self._counts[0] if self._counts is not None else None)
        self.refresh_labels()

    # ---- shared label pieces
    def _count_part(self, d: dict) -> str:
        if not d["visible"]:
            return "off"
        if self._counts is None:
            return "–"
        n = sum(self._counts[0].values())
        k = self._counts[1]
        return f"{n:,} plotted" + (f", {k:,} off" if k else "")

    def _layer_part(self) -> str:
        lyr = self.layer()
        if lyr is not None:
            return lyr.name()
        return "layer not in the project" if self.is_missing() else "no layer chosen"

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
            name = d["name"] or EMPTY_LAYER
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
        self._user_edit()

    def _on_type_field_edit(self, *args) -> None:
        if self._filling or self._frozen():
            return
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
    Properties > Symbology; the sheet follows." for a style of several items."""

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
        self.foot = _note(STYLE_FOOT)
        self.foot.setTextFormat(Qt.TextFormat.RichText)
        for w in (self.head, self.chips, self.off_note, self.foot):
            lay.addWidget(w)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
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
        self.foot.setHidden(not several)


# ---------------------------------------------------------------- an explorations row
class ExplorationRow(_PointRow):
    """One explorations layer: [visible] [line swatch] [name / "layer · label · k of n types · N plotted"] [⋯] over
    its editor: layer, legend name, look, label and type fields, types, and under "More: depths, water and range" the
    top, bottom and depth fields, "In elevation range", the water fields and the table of water levels."""

    DEFAULTS = POINT_LAYER_DEFAULTS
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

    def _build_editor(self, ed: QVBoxLayout) -> None:
        ed.addWidget(field_box("Layer", self.layer_combo))
        ed.addWidget(field_box("Legend name", self.name_edit))
        self.look_seg = _segmented([("Black", "black"), ("Gray", "gray"), ("Color", "color")],
                                   ["Black, like your own explorations", "Gray, to set this layer apart",
                                    "Each exploration in its color in this layer's style in QGIS"])
        ed.addWidget(field_box("Drawn in", self.look_seg))
        self.look_hint = _note(LOOK_HINT)
        ed.addWidget(self.look_hint)
        self.style_box = LayerStyleBox(self.editor)          # Color: what is read from the layer's style
        self.style_box.hide()
        ed.addWidget(self.style_box)
        ed.addWidget(pair(field_box("Label field", self.label_field), field_box("Type field", self.type_field)))
        ed.addWidget(field_box("Types", self.type_list, links=[self.btn_types_all, self._types_dot,
                                                               self.btn_types_none], note="plotted / in the layer"))

        self.more = Disclosure("More: depths, water and range")
        m = self.more
        self.more_hint = _note("")
        self.more_hint.setTextFormat(Qt.TextFormat.RichText)
        self.more_hint.hide()
        m.addWidget(self.more_hint)
        self.top_field = _numeric_field_combo("Top (collar or ground) elevation of each exploration, ft. Optional: "
                                              "LIDAR is used where it is empty.")
        self.bottom_elev_field = _numeric_field_combo("Bottom elevation of each exploration, ft. Optional: where it "
                                                      "is empty, the bottom is the top minus the total depth.")
        m.addWidget(pair(field_box("Top elevation", self.top_field),
                         field_box("Bottom elevation", self.bottom_elev_field)))
        self.depth_field = _numeric_field_combo("Total depth below the top, ft. Optional: used where there is no "
                                                "bottom elevation, and for the TD label.")
        # next to Total depth (0.3.5, his request: below the table it read as a water setting)
        self.in_range_box = FitCheckBox(IN_RANGE_TEXT, IN_RANGE_SHORT)
        self.in_range_box.setToolTip(IN_RANGE_TIP)
        self.depth_pair = pair(field_box("Total depth", self.depth_field), self.in_range_box)
        m.addWidget(self.depth_pair)
        self.range_hint = _note("Deeper ones stop at the frame with an arrow and their TD.")
        self.range_hint.hide()
        m.addWidget(self.range_hint)
        self.water_head = field_label("Water and screens")
        self.water_head.setObjectName("xsSubhead")
        m.addWidget(self.water_head)
        self.wl_field = _numeric_field_combo("Measured water level: elevation or depth, ft (see Levels are). Drawn "
                                             "as an open triangle joined to the middle of the screen.")
        self.wl_date_field = _field_combo("Date of the measured water level (any field type). Optional.")
        m.addWidget(pair(field_box("Measured level", self.wl_field), field_box("Date", self.wl_date_field)))
        self.atd_field = _numeric_field_combo("Water level at the time of drilling (ATD): elevation or depth, ft (see "
                                              "Levels are). Drawn as a filled triangle on the exploration line.")
        self.atd_date_field = _field_combo("Date of the ATD water level, usually the drilling date (any field type). "
                                           "Optional.")
        m.addWidget(pair(field_box("ATD level", self.atd_field), field_box("Date", self.atd_date_field)))
        self.wl_values = _segmented([("Elevations", "elevation"), ("Depths", "depth")],
                                    ["Water levels are elevations, ft",
                                     "Water levels are depths below the top of the exploration, ft"])
        self.wl_values.setToolTip("Applies to the measured and ATD fields and to the table of water levels")
        m.addWidget(field_box("Levels are", self.wl_values))
        self.screen_top_field = _numeric_field_combo("Top of the well screen (depth or elevation, see Screens are). "
                                                     "Optional.")
        self.screen_bottom_field = _numeric_field_combo("Bottom of the well screen (depth or elevation, see Screens "
                                                        "are). Optional.")
        m.addWidget(pair(field_box("Screen top", self.screen_top_field),
                         field_box("Screen bottom", self.screen_bottom_field)))
        # Elevations | Depths, as Levels are (0.3.5; the stored values and the default "depth" unchanged)
        self.screen_values = _segmented([("Elevations", "elevation"), ("Depths", "depth")],
                                        ["Elevations, ft", "Feet below the top of the exploration"])
        m.addWidget(field_box("Screens are", self.screen_values))
        self.wl_table = QgsMapLayerComboBox(self.editor)
        self.wl_table.setFilters(Qgis.LayerFilter.VectorLayer)
        self.wl_table.setAllowEmptyLayer(True, "(none)")
        self.wl_table.setToolTip(WL_TABLE_TIP)
        _narrow(self.wl_table)
        m.addWidget(field_box(WL_TABLE_LABEL, self.wl_table))
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
        tb.setSpacing(7)
        tb.addWidget(pair(field_box("Exploration name", self.wl_table_name_field),
                          field_box("Water level", self.wl_table_elev_field)))
        tb.addWidget(pair(field_box("Date", self.wl_table_date_field), field_box("Kind", self.wl_table_kind_field)))
        tb.addWidget(field_box("ATD when kind is", self.wl_atd_values))
        self.table_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.table_box.hide()
        m.addWidget(self.table_box)
        ed.addWidget(m)

    def _connect_editor(self) -> None:
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
        return G.guess_point_row(fields, pk, layer_name, saved=d, guess_fields=guess_fields, text_ok=text_ok)

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
        self._style = self._read_style(point_layer(d["layer_id"]))
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
        self.water_head.setEnabled(on)
        self.wl_date_field.setEnabled(on and bool(self.wl_field.currentField()))
        self.atd_date_field.setEnabled(on and bool(self.atd_field.currentField()))
        tbl = self.wl_table.currentLayer()
        self.table_box.setHidden(tbl is None)
        for _key, box, _num, _empty in self._table_boxes():
            box.setEnabled(on and tbl is not None)
        self.wl_atd_values.setEnabled(on and tbl is not None and bool(self.wl_table_kind_field.currentField()))
        self.range_hint.setHidden(self.in_range_box.isChecked())

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

    def refresh_labels(self) -> None:
        d = self.value()
        self._show_name(d)
        look = d["look"]
        self.style_box.set_style(self._style, missing=self.is_missing(), plotted=self._plotted_keys)
        self.style_box.setHidden(look != "color")
        self.look_hint.setHidden(look == "color")
        self.swatch.set_colors(self._swatch_colors(look))
        lyr = self.layer()
        parts = [self._layer_part()]
        if lyr is not None:
            if d["label_field"]:
                parts.append(d["label_field"])
            parts.append(self._types_part(d))
        if look != "black":
            parts.append("gray" if look == "gray" else "color from the layer style")
        parts.append(self._count_part(d))
        self.sub_label.setText(" · ".join(parts))
        self.more_hint.setText(self._more_hint_text(d))
        self.more_hint.setHidden(not self.more_hint.text())
        self.range_hint.setHidden(d["in_range"])

    def _more_hint_text(self, d: dict) -> str:
        if self.layer() is None:
            return ""
        water = any(d[k] for k in ("screen_top_field", "screen_bottom_field", "wl_field", "atd_field",
                                   "wl_table_id"))
        if not water:
            return "This layer has no water-level or screen fields, so none are drawn for it."
        return self._hint


# ---------------------------------------------------------------- an other-points row
class OtherPointsRow(_PointRow):
    """One layer of other points (seeps, springs...): [visible] [symbol] [name / "layer · elevation · N plotted"]
    [⋯] over its editor: layer, legend name, label and type fields, types, the symbol (shape, colour, size) and where
    each point sits (the ground line, the LIDAR at the point, or a field with what to do where it is empty)."""

    DEFAULTS = OTHER_POINT_DEFAULTS
    ROW_TIP = "Draw these points"

    def _make_swatch(self) -> QWidget:
        sw = SymbolSwatch(OTHER_POINT_DEFAULTS["shape"], OTHER_POINT_DEFAULTS["color"])
        sw.setToolTip("The symbol of these points")
        return sw

    def _clean(self, d: dict) -> dict:
        return clean_other_point(d) or copy.deepcopy(OTHER_POINT_DEFAULTS)

    def _make_type_field(self) -> QgsFieldComboBox:
        c = FieldComboWithNone("(none: every point)")
        c.setToolTip("Field of the types to plot (none: every point)")
        _narrow(c)
        return c

    def _build_editor(self, ed: QVBoxLayout) -> None:
        ed.addWidget(field_box("Layer", self.layer_combo))
        ed.addWidget(pair(field_box("Legend name", self.name_edit), field_box("Label field", self.label_field)))
        ed.addWidget(field_box("Type field", self.type_field))
        self.types_box = field_box("Types", self.type_list, links=[self.btn_types_all, self._types_dot,
                                                                   self.btn_types_none], note="plotted / in the layer")
        ed.addWidget(self.types_box)
        self.shape_seg = _segmented(SHAPE_CHOICES, [t for t, _v in SHAPE_CHOICES])
        for i, (_text, shape) in enumerate(SHAPE_CHOICES):
            self.shape_seg.setItemIcon(i, _SHAPE_SVG.format(SHAPE_ICONS[shape]))
        self.color_btn = QgsColorButton(self.editor)
        self.color_btn.setShowMenu(False)
        self.color_btn.setAllowOpacity(False)
        self.color_btn.setColorDialogTitle("Symbol colour")
        self.color_btn.setFixedSize(30, 24)
        self.color_btn.setToolTip("Colour of the symbol")
        self.size_spin = _spin(OTHER_SIZE_MIN, OTHER_SIZE_MAX, 1, 0.5, " pt")
        self.size_spin.setToolTip("Size of the symbol, points")
        sym = QWidget()
        sl = QHBoxLayout(sym)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        for box, stretch in ((field_box("Symbol", self.shape_seg), 15), (field_box("Colour", self.color_btn), 0),
                             (field_box("Size", self.size_spin), 8)):
            if stretch:
                box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            else:
                box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            sl.addWidget(box, stretch, Qt.AlignmentFlag.AlignBottom)
        sym.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        ed.addWidget(sym)
        self.elev_seg = _segmented(ELEV_CHOICES, ["On the ground line drawn along the section, just touching it",
                                                  "The LIDAR elevation at each point's own location",
                                                  "An elevation field of the layer, ft"])
        ed.addWidget(field_box("Elevation", self.elev_seg))
        self.elev_field = _numeric_field_combo("Elevation of each point, ft")
        self.empty_seg = _segmented(EMPTY_CHOICES, EMPTY_TIPS)
        self.elev_field_row = pair(field_box("Elevation field", self.elev_field),
                                   field_box("Where it is empty", self.empty_seg))
        self.elev_field_row.hide()
        ed.addWidget(self.elev_field_row)
        self.elev_hint = _note("")
        ed.addWidget(self.elev_hint)

    def _connect_editor(self) -> None:
        for seg in (self.shape_seg, self.elev_seg, self.empty_seg):
            seg.currentIndexChanged.connect(self._on_header_edit)
        self.color_btn.colorChanged.connect(self._on_header_edit)
        self.size_spin.valueChanged.connect(self._on_header_edit)
        self.elev_field.fieldChanged.connect(self._on_field_edit)

    def _field_boxes(self):
        return (("label_field", self.label_field, False, False), ("type_field", self.type_field, False, True),
                ("elev_field", self.elev_field, True, True))

    def _guess(self, fields, pk, layer_name, d, guess_fields, text_ok=None):
        return G.guess_other_row(fields, pk, layer_name, saved=d, guess_fields=guess_fields, text_ok=text_ok), ""

    def _header_value(self) -> dict:
        out = super()._header_value()
        size = float(self.size_spin.value())
        stored = float(self._stored.get("size", size))
        if abs(stored - size) <= 0.5 * 10.0 ** -self.size_spin.decimals() + 1e-9:
            size = stored                  # the box shows a stored 7.25 as 7.3: keep what was stored
        out.update(shape=self.shape_seg.currentData() or "asterisk", color=self.color_btn.color().name(),
                   size=size, elev=self.elev_seg.currentData() or "line",
                   elev_empty=self.empty_seg.currentData() or "line")
        return out

    def _set_header(self, d: dict) -> None:
        super()._set_header(d)
        _set_combo_data(self.shape_seg, d["shape"])
        self.color_btn.setColor(QColor(d["color"]))
        self.size_spin.setValue(d["size"])
        _set_combo_data(self.elev_seg, d["elev"])
        _set_combo_data(self.empty_seg, d["elev_empty"])

    def set_shared(self, *args, **kw) -> None:
        """Nothing shared enables an other-points box (kept so the dock can treat both kinds alike)."""

    def _sync_enabled(self) -> None:
        super()._sync_enabled()
        self.types_box.setHidden(not self.type_field.currentField())
        self.elev_field_row.setHidden(self.elev_seg.currentData() != "field")

    # ---- labels
    def how_text(self, d: Optional[dict] = None) -> str:
        """Where the points sit, as the subtitle says it."""
        d = d or self.value()
        if d["elev"] == "line":
            return "on the ground line"
        if d["elev"] == "lidar":
            return "LIDAR at the point"
        field = d["elev_field"] or "(no field)"
        return field + {"line": ", else on the ground line", "lidar": ", else LIDAR", "off": " only"}[d["elev_empty"]]

    def hint_text(self, d: Optional[dict] = None) -> str:
        d = d or self.value()
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

    def refresh_labels(self) -> None:
        d = self.value()
        self._show_name(d)
        self.swatch.set_symbol(d["shape"], d["color"])
        self.sub_label.setText(" · ".join([self._layer_part(), self.how_text(d), self._count_part(d)]))
        self.elev_hint.setText(self.hint_text(d))
        self.elev_field_row.setHidden(d["elev"] != "field")
        self.types_box.setHidden(not d["type_field"])
