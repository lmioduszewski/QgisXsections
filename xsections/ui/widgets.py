"""Reusable widgets of the XSections panel.

- Theme: the panel's colors, taken from the QGIS palette (navy bars in a light theme, the theme's highlight in
  a dark one), and panel_stylesheet(), a stylesheet whose rules are all scoped by objectName so that it only
  styles the panel's own widgets.
- CollapsibleSection: an uppercase header (caret, icon, title, summary chip) over a body.
- SegmentedControl: buttons for a short choice, with the QComboBox API the panel uses.
- field_box / pair / hrow: small uppercase labels above fields, two fields to a row.
- Disclosure: "More: ..." settings that are set once, folded inside a section.
- SurfaceRow: one other surface (a raster line besides the ground) in the Surfaces list, with its editor. Its source
  fields (raster, band) are hooks that mf6_dialog.ModelSurfaceRow replaces for a MODFLOW 6 model surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from qgis.core import Qgis, QgsProject, QgsRasterLayer
from qgis.gui import QgsColorButton, QgsDoubleSpinBox, QgsMapLayerComboBox, QgsRasterBandComboBox
from qgis.PyQt.QtCore import QByteArray, QEvent, QObject, QPointF, QRectF, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette, QPen, QPolygonF
from qgis.PyQt.QtWidgets import (QAbstractButton, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                                 QMenu, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..core.model import SURFACE_DEFAULTS, clean_surface

try:                                   # QtSvg ships with QGIS; the icons fall back to nothing without it
    from qgis.PyQt.QtSvg import QSvgRenderer
except ImportError:                    # pragma: no cover
    QSvgRenderer = None

CONTROL_H = 24                         # height of fields and segmented buttons, px


# ---------------------------------------------------------------- theme
def _mix(a: QColor, b: QColor, t: float) -> QColor:
    """`a` blended toward `b` by `t` (0 = a, 1 = b)."""
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


def css(c: QColor) -> str:
    """A color for a stylesheet (rgba() when it is translucent)."""
    if c.alpha() < 255:
        return f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()})"
    return c.name()


@dataclass
class Theme:
    dark: bool
    bar: QColor                # open section header, checked segment, primary button
    bar_hover: QColor
    bar_disabled: QColor
    on_bar: QColor             # text on the bar
    heading: QColor            # closed section header text
    ink: QColor
    muted: QColor              # field labels, readouts, sub lines
    disabled: QColor
    rule: QColor               # thin separators
    field: QColor              # field background
    field_line: QColor         # field border
    chip: QColor
    chip_ink: QColor
    chip_open: QColor          # chip on an open (bar) header
    warn: QColor
    warn_bg: QColor
    error: QColor
    link: QColor
    hover: QColor
    chip_on: QColor            # checked tool button
    panel2: QColor             # inline editor background


_THEMES: Dict[Tuple[str, ...], Theme] = {}


def theme_for(pal: QPalette) -> Theme:
    """The panel colors for a palette: the Water Quality look (navy bars) in a light theme; in a dark theme
    (window lightness < 128) the bars take the palette's highlight and the rest is mixed from the palette."""
    cr = QPalette.ColorRole
    win, txt, base = pal.color(cr.Window), pal.color(cr.WindowText), pal.color(cr.Base)
    hl, hl_txt = pal.color(cr.Highlight), pal.color(cr.HighlightedText)
    dis = pal.color(QPalette.ColorGroup.Disabled, cr.WindowText)
    key = tuple(c.name() for c in (win, txt, base, hl, hl_txt, dis))
    cached = _THEMES.get(key)
    if cached is not None:
        return cached
    white = QColor("#ffffff")
    if win.lightness() < 128:
        t = Theme(dark=True, bar=hl, bar_hover=hl.lighter(115), bar_disabled=_mix(hl, win, 0.55),
                  on_bar=hl_txt if hl_txt.lightness() > 160 else white,
                  heading=_mix(txt, hl, 0.22), ink=txt, muted=_mix(txt, win, 0.36), disabled=dis,
                  rule=_mix(win, txt, 0.16), field=base, field_line=_mix(win, txt, 0.28),
                  chip=_mix(win, txt, 0.15), chip_ink=_mix(txt, win, 0.12), chip_open=QColor(255, 255, 255, 46),
                  warn=QColor("#e6b65c"), warn_bg=QColor("#3b2f15"), error=QColor("#ff8a7a"),
                  link=_mix(hl, white, 0.45), hover=QColor(255, 255, 255, 22), chip_on=_mix(win, hl, 0.35),
                  panel2=_mix(win, txt, 0.06))
    else:
        t = Theme(dark=False, bar=QColor("#193340"), bar_hover=QColor("#21414f"), bar_disabled=QColor("#9aa8b0"),
                  on_bar=white, heading=QColor("#193340"), ink=txt, muted=QColor("#5a6b74"), disabled=dis,
                  rule=QColor("#d3dadf"), field=base, field_line=QColor("#c3ccd2"),
                  chip=QColor("#dce3e7"), chip_ink=QColor("#44555e"), chip_open=QColor(255, 255, 255, 46),
                  warn=QColor("#9a6510"), warn_bg=QColor("#f6eedd"), error=QColor("#c0392b"),
                  link=QColor("#446f85"), hover=QColor(122, 146, 158, 40), chip_on=QColor("#dde7ed"),
                  panel2=QColor("#eef2f4"))
    _THEMES[key] = t
    return t


def panel_stylesheet(t: Theme) -> str:
    """The panel's stylesheet. Every rule names an objectName, so only the panel's own widgets change."""
    return f"""
QLabel#xsFieldLabel {{ color: {css(t.muted)}; }}
QLabel#xsFieldLabel:disabled {{ color: {css(t.disabled)}; }}
QLabel#xsReadout {{ color: {css(t.muted)}; border: none; border-top: 1px dashed {css(t.rule)}; padding-top: 4px; }}
QLabel#xsNote {{ color: {css(t.muted)}; }}
QLabel#xsMuted {{ color: {css(t.muted)}; }}
QLabel#xsMuted:disabled {{ color: {css(t.disabled)}; }}
QToolButton#xsSegButton {{ background: {css(t.field)}; color: {css(t.ink)}; border: 1px solid {css(t.field_line)};
    border-left-width: 0px; border-radius: 0px; padding: 0px 2px; }}
QToolButton#xsSegButton[segpos="first"] {{ border-left-width: 1px; border-top-left-radius: 4px;
    border-bottom-left-radius: 4px; }}
QToolButton#xsSegButton[segpos="last"] {{ border-top-right-radius: 4px; border-bottom-right-radius: 4px; }}
QToolButton#xsSegButton[segpos="only"] {{ border-left-width: 1px; border-radius: 4px; }}
QToolButton#xsSegButton:hover:!checked {{ background: {css(t.hover)}; }}
QToolButton#xsSegButton:checked {{ background: {css(t.bar)}; color: {css(t.on_bar)}; border-color: {css(t.bar)}; }}
QToolButton#xsSegButton:disabled {{ color: {css(t.disabled)}; }}
QToolButton#xsSegButton:checked:disabled {{ background: {css(t.bar_disabled)}; color: {css(t.field)};
    border-color: {css(t.bar_disabled)}; }}
QToolButton#xsTool {{ background: {css(t.field)}; color: {css(t.ink)}; border: 1px solid {css(t.field_line)};
    border-radius: 4px; padding: 1px 5px; }}
QToolButton#xsTool:hover {{ border-color: {css(t.link)}; }}
QToolButton#xsTool:checked {{ background: {css(t.chip_on)}; border-color: {css(t.link)}; }}
QToolButton#xsTool:disabled {{ color: {css(t.disabled)}; }}
QToolButton#xsTool::menu-indicator {{ image: none; width: 0px; }}
QToolButton#xsRowMenu {{ background: {css(t.field)}; color: {css(t.ink)}; border: 1px solid {css(t.field_line)};
    border-radius: 3px; padding: 0px; }}
QToolButton#xsRowMenu:hover {{ border-color: {css(t.link)}; }}
QToolButton#xsRowMenu::menu-indicator {{ image: none; width: 0px; }}
QToolButton#xsLink {{ background: transparent; color: {css(t.link)}; border: none; padding: 0px 1px; }}
QToolButton#xsLink:hover {{ text-decoration: underline; }}
QToolButton#xsLink:disabled {{ color: {css(t.disabled)}; }}
QPushButton#xsPrimary {{ background: {css(t.bar)}; color: {css(t.on_bar)}; border: none; border-radius: 4px;
    font-weight: 600; padding: 0px 10px; }}
QPushButton#xsPrimary:hover {{ background: {css(t.bar_hover)}; }}
QPushButton#xsPrimary:pressed {{ background: {css(t.bar.darker(115))}; }}
QPushButton#xsPrimary:disabled {{ background: {css(t.bar_disabled)}; }}
QFrame#xsSurfaceList {{ background: {css(t.field)}; border: 1px solid {css(t.field_line)}; border-radius: 3px; }}
QFrame#xsSurfaceRow {{ background: transparent; border: none; border-top: 1px solid {css(t.rule)}; }}
QFrame#xsGroundRow {{ background: transparent; border: none; }}
QFrame#xsSurfaceEditor {{ background: {css(t.panel2)}; border: none; border-top: 1px solid {css(t.rule)}; }}
QFrame#xsMoreBody {{ border: none; border-left: 2px solid {css(t.rule)}; }}
"""


# ---------------------------------------------------------------- section icons (monochrome, like the mockup)
_SVG_HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="currentColor" '
             'stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round">')
ICONS = {
    "line": '<path d="M1.5 12.5L5.5 5l4 4 5-6.5"/><circle cx="1.5" cy="12.5" r="1.2" fill="currentColor"/>'
            '<circle cx="14.5" cy="2.5" r="1.2" fill="currentColor"/>',
    "surfaces": '<path d="M1 4.5c2.5-2 4.5 1 7-.5s4-2 7 0M1 9c2.5-1.6 4.5.8 7-.4s4-1.6 7 0M1 13.5h14"/>',
    "explorations": '<circle cx="8" cy="6" r="3.2"/><path d="M8 9.2V15M5 15h6"/>',
    "depths": '<path d="M8 2v12M5 2h6M5 14h6"/>',
    "screens": '<path d="M3.5 3h9L8 9.5z"/><path d="M2 12h12M5 14.5h6"/>',
    "scale": '<rect x="1" y="5" width="14" height="6" rx=".5"/><path d="M4 5v2.6M7 5v1.6M10 5v2.6M13 5v1.6"/>',
    "style": '<path d="M8 1.5a6.5 6.5 0 1 0 0 13c1.2 0 1.5-.8 1.1-1.6-.5-1 .1-1.9 1.2-1.9h1.6a2.6 2.6 0 0 0 '
             '2.6-2.6C14.5 4.5 11.6 1.5 8 1.5z"/><circle cx="5" cy="7" r=".9" fill="currentColor"/>'
             '<circle cx="7.6" cy="4.4" r=".9" fill="currentColor"/><circle cx="10.8" cy="5.4" r=".9" '
             'fill="currentColor"/>',
}
_RENDERERS: Dict[Tuple[str, str], Any] = {}


def _icon_renderer(name: str, color: str):
    if QSvgRenderer is None or name not in ICONS:
        return None
    key = (name, color)
    r = _RENDERERS.get(key)
    if r is None:
        svg = (_SVG_HEAD + ICONS[name] + "</svg>").replace("currentColor", color)
        r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        _RENDERERS[key] = r
    return r if r.isValid() else None


def _scaled_font(base: QFont, factor: float, weight: Optional[QFont.Weight] = None, spacing: float = 0.0) -> QFont:
    f = QFont(base)
    if f.pointSizeF() > 0:
        f.setPointSizeF(max(6.5, f.pointSizeF() * factor))
    elif f.pixelSize() > 0:
        f.setPixelSize(max(9, round(f.pixelSize() * factor)))
    if weight is not None:
        f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100.0 + spacing)
    return f


# ---------------------------------------------------------------- collapsible section
class SectionHeader(QWidget):
    """Clickable header: caret, icon, UPPERCASE title and a summary chip at the right (amber with a dot when
    something is missing). Open: a full-width bar in the theme's bar color with white text."""

    clicked = pyqtSignal()
    HEIGHT = 28

    def __init__(self, title: str, icon: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsSectionHeader")
        self._title = title
        self._icon = icon
        self._chip = ""
        self._warn = False
        self._open = False
        self._hover = False
        self.first = False             # no rule above the first header
        self.last = False              # a rule under the last header while it is closed
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.HEIGHT)
        self._sync_accessible()

    # ---- state
    def title(self) -> str:
        return self._title

    def setChip(self, text: str, warn: bool = False) -> None:
        if (text, warn) == (self._chip, self._warn):
            return
        self._chip, self._warn = text, bool(warn)
        self._sync_accessible()
        self.update()

    def chipText(self) -> str:
        return self._chip

    def chipWarn(self) -> bool:
        return self._warn

    def isOpen(self) -> bool:
        return self._open

    def setOpen(self, on: bool) -> None:
        self._open = bool(on)
        self._sync_accessible()
        self.update()

    def _sync_accessible(self) -> None:
        state = "open" if self._open else "closed"
        self.setAccessibleName(f"{self._title} ({state})" + (f": {self._chip}" if self._chip else ""))
        self.setToolTip(self._chip)

    # ---- size
    def sizeHint(self) -> QSize:
        return QSize(220, self.HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return QSize(60, self.HEIGHT)

    def _title_font(self) -> QFont:
        return _scaled_font(self.font(), 0.92, QFont.Weight.Bold, 4.0)

    def _chip_font(self) -> QFont:
        return _scaled_font(self.font(), 0.86, QFont.Weight.DemiBold if self._warn else QFont.Weight.Normal)

    # ---- events
    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicked.emit()
            return
        super().keyPressEvent(e)

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e) -> None:
        t = theme_for(self.palette())
        p = QPainter(self)
        w, h = self.width(), self.height()
        if self._open:
            p.fillRect(self.rect(), t.bar_hover if self._hover else t.bar)
        elif self._hover:
            p.fillRect(self.rect(), t.hover)
        if not self._open:
            p.setPen(QPen(t.rule, 1))
            if not self.first:
                p.drawLine(0, 0, w, 0)
            if self.last:
                p.drawLine(0, h - 1, w, h - 1)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fg = t.on_bar if self._open else t.heading
        cy = h / 2.0
        x = 10.0
        # caret
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fg)
        if self._open:
            tri = [QPointF(x, cy - 2.0), QPointF(x + 7.0, cy - 2.0), QPointF(x + 3.5, cy + 2.5)]
        else:
            tri = [QPointF(x + 1.5, cy - 3.5), QPointF(x + 6.0, cy), QPointF(x + 1.5, cy + 3.5)]
        p.drawPolygon(QPolygonF(tri))
        x += 7.0 + 7.0
        # icon
        rend = _icon_renderer(self._icon, fg.name())
        if rend is not None:
            rend.render(p, QRectF(x, cy - 7.0, 14.0, 14.0))
            x += 14.0 + 7.0
        right = w - 8.0
        # title (elided only when even a short chip cannot fit)
        tf = self._title_font()
        fm = QFontMetrics(tf)
        title = self._title.upper()
        room = right - x - (44.0 if self._chip else 0.0)
        title = fm.elidedText(title, Qt.TextElideMode.ElideRight, int(max(0.0, room)))
        tw = fm.horizontalAdvance(title)
        p.setFont(tf)
        p.setPen(fg)
        p.drawText(QRectF(x, 0.0, tw + 4.0, h), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                   title)
        x += tw + 10.0
        # chip
        if self._chip:
            cf = self._chip_font()
            cfm = QFontMetrics(cf)
            pad, dot = 7.0, (10.0 if self._warn else 0.0)
            natural = cfm.horizontalAdvance(self._chip) + 2 * pad + dot
            cw = min(natural, right - x)
            if cw >= 24.0:
                text = cfm.elidedText(self._chip, Qt.TextElideMode.ElideRight, int(cw - 2 * pad - dot))
                ch = float(min(17, h - 8))
                rect = QRectF(right - cw, cy - ch / 2.0, cw, ch)
                if self._warn:
                    bg, ink = t.warn_bg, t.warn
                elif self._open:
                    bg, ink = t.chip_open, t.on_bar
                else:
                    bg, ink = t.chip, t.chip_ink
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(bg)
                p.drawRoundedRect(rect, ch / 2.0, ch / 2.0)
                tx = rect.left() + pad
                if self._warn:
                    p.setBrush(ink)
                    p.drawEllipse(QPointF(tx + 3.0, cy), 3.0, 3.0)
                    tx += dot
                p.setFont(cf)
                p.setPen(ink)
                p.drawText(QRectF(tx, rect.top(), rect.right() - pad - tx + 2.0, ch),
                           int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        if self.hasFocus():
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            pen = QPen(fg, 1, Qt.PenStyle.DotLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.end()


class CollapsibleSection(QWidget):
    """A section of the panel: SectionHeader over a body. Collapsed when created. setCollapsed / isCollapsed
    follow QgsCollapsibleGroupBox."""

    collapsedStateChanged = pyqtSignal(bool)

    def __init__(self, title: str, icon: str = "", object_name: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        self.header = SectionHeader(title, icon, self)
        self.body = QFrame(self)
        self.body.setObjectName("xsSectionBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(10, 8, 10, 12)
        self.body_layout.setSpacing(7)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(self.body)
        self._collapsed = True
        self.body.hide()
        self.header.clicked.connect(self.toggle)

    def addWidget(self, w: QWidget) -> QWidget:
        self.body_layout.addWidget(w)
        return w

    def title(self) -> str:
        return self.header.title()

    def isCollapsed(self) -> bool:
        return self._collapsed

    def setCollapsed(self, collapsed: bool) -> None:
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self.body.setVisible(not collapsed)
        self.header.setOpen(not collapsed)
        self.collapsedStateChanged.emit(collapsed)

    def toggle(self) -> None:
        self.setCollapsed(not self._collapsed)

    def setChip(self, text: str, warn: bool = False) -> None:
        self.header.setChip(text, warn)

    def chipText(self) -> str:
        return self.header.chipText()

    def chipWarn(self) -> bool:
        return self.header.chipWarn()


# ---------------------------------------------------------------- segmented control
class SegmentedControl(QWidget):
    """Buttons side by side for a short choice, with the QComboBox API the panel uses: addItem(text, data),
    count, itemText, itemData, findData, findText, currentIndex, setCurrentIndex, currentData, currentText,
    and the signals currentIndexChanged(int) (also for programmatic changes) and activated(int) (clicks).
    setItemShortText gives a button a shorter text, shown while the full texts do not all fit."""

    currentIndexChanged = pyqtSignal(int)
    activated = pyqtSignal(int)

    def __init__(self, items: Sequence[Tuple[str, Any]] = (), parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsSegmented")
        self._texts: List[str] = []
        self._short: List[str] = []
        self._data: List[Any] = []
        self._buttons: List[QToolButton] = []
        self._current = -1
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(CONTROL_H)
        for text, data in items:
            self.addItem(text, data)

    # ---- items
    def addItem(self, text: str, data: Any = None) -> None:
        i = len(self._texts)
        b = QToolButton(self)
        b.setObjectName("xsSegButton")
        b.setText(text)
        b.setCheckable(True)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        b.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        b.setFixedHeight(CONTROL_H)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.setFont(_scaled_font(self.font(), 0.95))
        b.clicked.connect(lambda _checked=False, idx=i: self._on_clicked(idx))
        self._texts.append(text)
        self._short.append("")
        self._data.append(data)
        self._buttons.append(b)
        self._lay.addWidget(b, 1)
        self._update_positions()
        if self._current < 0:
            self.setCurrentIndex(0)
        else:
            self._sync_checks()

    def addItems(self, texts: Sequence[str]) -> None:
        for t in texts:
            self.addItem(t)

    def clear(self) -> None:
        for b in self._buttons:
            b.setParent(None)
            b.deleteLater()
        self._texts, self._short, self._data, self._buttons = [], [], [], []
        if self._current != -1:
            self._current = -1
            self.currentIndexChanged.emit(-1)

    def count(self) -> int:
        return len(self._texts)

    def itemText(self, i: int) -> str:
        return self._texts[i] if 0 <= i < len(self._texts) else ""

    def setItemText(self, i: int, text: str) -> None:
        if 0 <= i < len(self._texts):
            self._texts[i] = text
            self._buttons[i].setText(text)
            self._fit_texts()

    def setItemShortText(self, i: int, text: str) -> None:
        """A shorter text for button `i` (its tooltip should say the full one), used while the full texts do not
        all fit."""
        if 0 <= i < len(self._short):
            self._short[i] = text
            self._fit_texts()

    def _fit_texts(self) -> None:
        if not any(self._short) or not self._buttons:
            return
        room = self.width() / len(self._buttons)
        fm = QFontMetrics(self._buttons[0].font())
        full = all(fm.horizontalAdvance(t) + 6 <= room for t in self._texts)
        for b, text, short in zip(self._buttons, self._texts, self._short):
            b.setText(text if full or not short else short)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._fit_texts()

    def itemData(self, i: int, role: Any = None) -> Any:
        return self._data[i] if 0 <= i < len(self._data) else None

    def setItemToolTip(self, i: int, tip: str) -> None:
        if 0 <= i < len(self._buttons):
            self._buttons[i].setToolTip(tip)

    def findData(self, data: Any, *args) -> int:
        for i, d in enumerate(self._data):
            if d == data:
                return i
        return -1

    def findText(self, text: str, *args) -> int:
        try:
            return self._texts.index(text)
        except ValueError:
            return -1

    # ---- current
    def currentIndex(self) -> int:
        return self._current

    def currentData(self, role: Any = None) -> Any:
        return self.itemData(self._current)

    def currentText(self) -> str:
        return self.itemText(self._current)

    def setCurrentIndex(self, i: int) -> None:
        i = int(i)
        if not -1 <= i < len(self._texts):
            return
        if i == self._current:
            self._sync_checks()
            return
        self._current = i
        self._sync_checks()
        self.currentIndexChanged.emit(i)

    def buttons(self) -> List[QToolButton]:
        return list(self._buttons)

    def _on_clicked(self, i: int) -> None:
        changed = i != self._current
        self.setCurrentIndex(i)
        if not changed:
            self._sync_checks()          # a click on the chosen button keeps it chosen
        self.activated.emit(i)

    def _sync_checks(self) -> None:
        for j, b in enumerate(self._buttons):
            b.setChecked(j == self._current)

    def _update_positions(self) -> None:
        n = len(self._buttons)
        for j, b in enumerate(self._buttons):
            pos = "only" if n == 1 else ("first" if j == 0 else ("last" if j == n - 1 else "mid"))
            if b.property("segpos") != pos:
                b.setProperty("segpos", pos)
                b.style().unpolish(b)
                b.style().polish(b)

    def minimumSizeHint(self) -> QSize:
        return QSize(16 * max(1, len(self._buttons)), CONTROL_H)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        w = sum(fm.horizontalAdvance(t) + 14 for t in self._texts) or 60
        return QSize(w, CONTROL_H)


# ---------------------------------------------------------------- small pieces
class _FollowEnabled(QObject):
    """Keeps a field label enabled exactly when its field is (so a disabled field's label greys out too)."""

    def __init__(self, label: QWidget, widget: QWidget):
        super().__init__(label)
        self._label = label
        widget.installEventFilter(self)
        label.setEnabled(widget.isEnabled())

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() == QEvent.Type.EnabledChange:
            try:
                self._label.setEnabled(obj.isEnabled())
            except RuntimeError:
                pass
        return False


def field_label(text: str) -> QLabel:
    """The small UPPERCASE semibold label above a field."""
    lab = QLabel(text.upper())
    lab.setObjectName("xsFieldLabel")
    lab.setFont(_scaled_font(lab.font(), 0.84, QFont.Weight.DemiBold, 3.5))
    lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    lab.setToolTip(text)
    return lab


def field_box(label: str, widget: QWidget, links: Sequence[QWidget] = ()) -> QWidget:
    """`widget` under its label; `links` (small link buttons) sit at the right of the label line."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    lab = None
    if links:
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(3)
        lab = field_label(label)
        head.addWidget(lab, 1)
        for x in links:
            head.addWidget(x, 0)
        lay.addLayout(head)
    elif label:
        lab = field_label(label)
        lay.addWidget(lab)
    lay.addWidget(widget)
    if lab is not None:
        _FollowEnabled(lab, widget)
    w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    return w


def pair(left: Optional[QWidget], right: Optional[QWidget], stretch: Tuple[int, int] = (1, 1)) -> QWidget:
    """Two fields side by side, sharing the width by `stretch` (equal halves by default), bottoms aligned."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    for x, st in ((left, stretch[0]), (right, stretch[1])):
        if x is None:
            x = QWidget()
        x.setSizePolicy(QSizePolicy.Policy.Ignored, x.sizePolicy().verticalPolicy())
        lay.addWidget(x, st, Qt.AlignmentFlag.AlignBottom)
    w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    return w


def hrow(*widgets, spacing: int = 5, equal: bool = True) -> QWidget:
    """Widgets in a row (strings become muted labels). `equal`: the widgets share the width equally."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for x in widgets:
        if isinstance(x, str):
            lab = QLabel(x)
            lab.setObjectName("xsMuted")
            lay.addWidget(lab, 0)
        elif x is None:
            lay.addStretch(1)
        else:
            if equal:
                x.setSizePolicy(QSizePolicy.Policy.Ignored, x.sizePolicy().verticalPolicy())
            lay.addWidget(x, 1)
    w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    return w


def checkbox_grid(boxes: Sequence[QWidget], columns: int = 2) -> QWidget:
    from qgis.PyQt.QtWidgets import QGridLayout
    w = QWidget()
    g = QGridLayout(w)
    g.setContentsMargins(0, 0, 0, 0)
    g.setHorizontalSpacing(8)
    g.setVerticalSpacing(4)
    for i, b in enumerate(boxes):
        b.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        g.addWidget(b, i // columns, i % columns)
    for c in range(columns):
        g.setColumnStretch(c, 1)
    w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    return w


def link_button(text: str, tooltip: str = "") -> QToolButton:
    b = QToolButton()
    b.setObjectName("xsLink")
    b.setText(text)
    b.setToolTip(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setAutoRaise(True)
    b.setFont(_scaled_font(b.font(), 0.9))
    return b


class ElidedLabel(QWidget):
    """One line of text, elided at the right (or `elide`: in the middle, for a file path) when there is no room.
    `small`: the muted sub-line style; `warn`: amber (a missing layer)."""

    def __init__(self, text: str = "", small: bool = False, parent: Optional[QWidget] = None,
                 elide: Qt.TextElideMode = Qt.TextElideMode.ElideRight):
        super().__init__(parent)
        self._text = text
        self._small = small
        self._warn = False
        self._bold = False
        self._muted = False
        self._elide = elide
        if small:
            self.setFont(_scaled_font(self.font(), 0.86))
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(QFontMetrics(self.font()).height() + 1)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self.setToolTip(text if self._small else "")
            self.update()

    def setWarn(self, warn: bool) -> None:
        if bool(warn) != self._warn:
            self._warn = bool(warn)
            self.update()

    def isWarn(self) -> bool:
        return self._warn

    def setMuted(self, muted: bool) -> None:
        """The muted color without the small font (e.g. a placeholder)."""
        if bool(muted) != self._muted:
            self._muted = bool(muted)
            self.update()

    def setBold(self, bold: bool) -> None:
        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
        self.setFont(f)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self._text) + 2, fm.height() + 1)

    def minimumSizeHint(self) -> QSize:
        return QSize(12, QFontMetrics(self.font()).height() + 1)

    def paintEvent(self, _e) -> None:
        t = theme_for(self.palette())
        p = QPainter(self)
        if self._warn:
            color = t.warn
        elif self._small or self._muted:
            color = t.muted
        elif not self.isEnabled():
            color = t.disabled
        else:
            color = self.palette().color(QPalette.ColorRole.Text)
        p.setPen(color)
        p.setFont(self.font())
        text = QFontMetrics(self.font()).elidedText(self._text, self._elide, self.width())
        p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        p.end()


class ClickableArea(QWidget):
    """A plain area that emits clicked() (mouse, or Space / Enter with the keyboard)."""

    clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicked.emit()
            return
        super().keyPressEvent(e)


class Swatch(QWidget):
    """A small filled rectangle (a fixed line color) or dot (the ground's 'always drawn' mark)."""

    def __init__(self, color: Optional[str] = None, dot: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._color = QColor(color) if color else None
        self._dot = dot
        self.setFixedSize(14 if dot else 26, 18 if not dot else 14)

    def paintEvent(self, _e) -> None:
        t = theme_for(self.palette())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._dot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(t.muted)
            p.drawEllipse(QPointF(self.width() / 2.0, self.height() / 2.0), 3.0, 3.0)
        else:
            p.setPen(QPen(t.field_line, 1))
            p.setBrush(self._color or t.ink)
            p.drawRoundedRect(QRectF(2.5, 3.5, self.width() - 5.0, self.height() - 7.0), 2.0, 2.0)
        p.end()


# ---------------------------------------------------------------- "More: ..." disclosure
class _DisclosureButton(QAbstractButton):
    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFont(_scaled_font(self.font(), 0.9, QFont.Weight.DemiBold))
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(QFontMetrics(self.font()).height() + 4)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self.text()) + 24, fm.height() + 4)

    def minimumSizeHint(self) -> QSize:
        return QSize(40, QFontMetrics(self.font()).height() + 4)

    def paintEvent(self, _e) -> None:
        t = theme_for(self.palette())
        p = QPainter(self)
        h = self.height()
        color = t.link if self.isEnabled() else t.disabled
        p.fillRect(QRectF(1.0, 1.0, 2.0, h - 2.0), color if self.isChecked() else t.field_line)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        cy, x = h / 2.0, 10.0
        if self.isChecked():
            tri = [QPointF(x, cy - 1.8), QPointF(x + 6.0, cy - 1.8), QPointF(x + 3.0, cy + 2.2)]
        else:
            tri = [QPointF(x + 1.0, cy - 3.0), QPointF(x + 5.0, cy), QPointF(x + 1.0, cy + 3.0)]
        p.drawPolygon(QPolygonF(tri))
        p.setPen(color)
        p.setFont(self.font())
        fm = QFontMetrics(self.font())
        text = fm.elidedText(self.text(), Qt.TextElideMode.ElideRight, int(self.width() - x - 10))
        p.drawText(QRectF(x + 9.0, 0.0, self.width() - x - 9.0, h),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        if self.hasFocus():
            p.setPen(QPen(color, 1, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(x + 7.0, 0.5, fm.horizontalAdvance(text) + 4.0, h - 1.0))
        p.end()


class Disclosure(QWidget):
    """Settings set once, folded under a "More: ..." link inside a section (folded when created)."""

    toggled = pyqtSignal(bool)

    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.button = _DisclosureButton(text, self)
        self.body = QFrame(self)
        self.body.setObjectName("xsMoreBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(11, 6, 0, 2)
        self.body_layout.setSpacing(7)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.button)
        lay.addWidget(self.body)
        self.body.hide()
        self.button.toggled.connect(self._on_toggled)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def addWidget(self, w: QWidget) -> QWidget:
        self.body_layout.addWidget(w)
        return w

    def text(self) -> str:
        return self.button.text()

    def isExpanded(self) -> bool:
        return self.button.isChecked()

    def setExpanded(self, on: bool) -> None:
        self.button.setChecked(bool(on))

    def _on_toggled(self, on: bool) -> None:
        self.body.setVisible(on)
        self.toggled.emit(on)


# ---------------------------------------------------------------- surfaces
STYLE_WORDS = {"solid": "solid", "dash": "dashed", "dot": "dotted"}
SURFACE_UNITS = [("Auto", "auto"), ("Feet", "ft"), ("US survey feet", "ftUS"), ("Meters", "m")]


def _narrow_combo(combo: QComboBox, chars: int = 6) -> None:
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(chars)
    combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)


class SurfaceRow(QFrame):
    """One other surface in the Surfaces list: [visible] [color] [name / "layer · band · style · mode"] [⋯],
    and under it an editor that opens when the name is clicked. value() is a dict with every key of
    SURFACE_DEFAULTS, in that order; the keys this row does not show (another source's) are kept as they were set.
    A surface whose raster is no longer in the project keeps its layer_id (the name turns amber), so the panel can
    say so instead of quietly drawing another raster.

    The editor holds the source's own fields (here a raster and its band; `_build_source` and the other source
    hooks, overridden by mf6_dialog.ModelSurfaceRow for a MODFLOW 6 model) over the common ones: name, line style,
    width, draw as, units, include in range and marks."""

    changed = pyqtSignal()
    moveRequested = pyqtSignal(int)        # -1 up, +1 down
    removeRequested = pyqtSignal()
    SOURCE = "raster"                      # the `source` key this row writes

    def __init__(self, data: Optional[dict] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsSurfaceRow")
        self._applying = 0
        self._removing = False             # the project is removing layers: the combo's moves are not choices
        self._stored: Dict[str, Any] = dict(SURFACE_DEFAULTS)   # every key as last set (kept when not shown)
        self._layer_id = ""
        self._band = 1
        self._color_text = SURFACE_DEFAULTS["color"]

        line = QWidget(self)
        ll = QHBoxLayout(line)
        ll.setContentsMargins(6, 4, 6, 4)
        ll.setSpacing(6)
        self.visible_box = QCheckBox(line)
        self.visible_box.setToolTip("Draw this surface")
        self.color_btn = QgsColorButton(line)
        self.color_btn.setShowMenu(False)
        self.color_btn.setAllowOpacity(False)
        self.color_btn.setColorDialogTitle("Surface line color")
        self.color_btn.setFixedSize(26, 18)
        self.color_btn.setToolTip("Line color")
        self.name_area = ClickableArea(line)
        self.name_area.setToolTip("Show or hide this surface's settings")
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
        ll.addWidget(self.color_btn, 0)
        ll.addWidget(self.name_area, 1)
        ll.addWidget(self.menu_btn, 0)

        self.editor = QFrame(self)
        self.editor.setObjectName("xsSurfaceEditor")
        ed = QVBoxLayout(self.editor)
        ed.setContentsMargins(28, 7, 8, 9)
        ed.setSpacing(7)
        self._build_source(ed)
        self.name_edit = QLineEdit(self.editor)
        self.name_edit.setToolTip("Name in the legend (empty: the layer name)")
        self.style_seg = SegmentedControl([("Solid", "solid"), ("Dash", "dash"), ("Dot", "dot")], self.editor)
        self.width_spin = QgsDoubleSpinBox(self.editor)
        self.width_spin.setRange(0.25, 4.0)
        self.width_spin.setSingleStep(0.25)
        self.width_spin.setDecimals(2)
        self.width_spin.setSuffix(" pt")
        self.width_spin.setShowClearButton(False)
        self.width_spin.setKeyboardTracking(False)
        self.width_spin.setToolTip("Line width, points")
        self.mode_seg = SegmentedControl([("Smooth", "smooth"), ("Cells", "cells")], self.editor)
        self.mode_seg.setItemToolTip(0, "Interpolated between cell centers")
        self.mode_seg.setItemToolTip(1, "Flat across each cell, stepping at cell edges (model layers)")
        self.units_combo = QComboBox(self.editor)
        for text, unit in SURFACE_UNITS:
            self.units_combo.addItem(text, unit)
        _narrow_combo(self.units_combo, 4)
        self.units_combo.setToolTip("Elevation units of this raster (Auto: from the layer)")
        self.in_range_box = QCheckBox("Include in the elevation range", self.editor)
        self.in_range_box.setToolTip("Unticked, the surface does not widen the automatic elevation range; it is "
                                     "clipped at the frame")
        self.marks_box = QCheckBox("▽ marks along the line", self.editor)
        self.marks_box.setToolTip("Water-table triangles along the surface")
        ed.addWidget(field_box("Name", self.name_edit))
        ed.addWidget(pair(field_box("Line", self.style_seg), field_box("Width", self.width_spin)))
        ed.addWidget(pair(field_box("Draw as", self.mode_seg), field_box("Units", self.units_combo)))
        ed.addWidget(self.in_range_box)
        ed.addWidget(self.marks_box)
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
        self.visible_box.toggled.connect(self._emit)
        self.color_btn.colorChanged.connect(self._emit)
        self.name_edit.textChanged.connect(self._emit)
        self.style_seg.currentIndexChanged.connect(self._emit)
        self.width_spin.valueChanged.connect(self._emit)
        self.mode_seg.currentIndexChanged.connect(self._emit)
        self.units_combo.currentIndexChanged.connect(self._emit)
        self.in_range_box.toggled.connect(self._emit)
        self.marks_box.toggled.connect(self._emit)
        self._connect_source()
        self.set_value(data or {})

    # ---- the source's own fields (a raster and its band); overridden for other sources
    def _build_source(self, ed: QVBoxLayout) -> None:
        """Add the source's fields to the editor layout `ed` (above the common fields)."""
        self.layer_combo = QgsMapLayerComboBox(self.editor)
        self.layer_combo.setFilters(Qgis.LayerFilter.RasterLayer)
        self.layer_combo.setAllowEmptyLayer(True, "(choose a raster)")
        _narrow_combo(self.layer_combo)
        self.band_combo = QgsRasterBandComboBox(self.editor)
        _narrow_combo(self.band_combo, 4)
        ed.addWidget(pair(field_box("Raster", self.layer_combo), field_box("Band", self.band_combo)))

    def _connect_source(self) -> None:
        self.layer_combo.layerChanged.connect(self._on_layer_changed)
        self.band_combo.bandChanged.connect(self._emit)

    def _source_value(self) -> dict:
        """The keys the source's fields set (merged over the stored dict by value())."""
        lyr = self.layer_combo.currentLayer()
        band = self.band_combo.currentBand() if lyr is not None else -1
        return dict(source=self.SOURCE, layer_id=self._layer_id,
                    band=int(band) if band and band >= 1 else int(self._band))

    def _set_source_value(self, d: dict) -> None:
        """Show the source's keys of the cleaned dict `d` (called inside set_value, signals muted)."""
        self._layer_id, self._band = d["layer_id"], d["band"]
        self._sync_layer_combo()
        if self.layer_combo.currentLayer() is not None:
            self.band_combo.setBand(d["band"])

    # ---- value
    def value(self) -> dict:
        color = self.color_btn.color()
        text = self._color_text if QColor(self._color_text).name() == color.name() else color.name()
        out = dict(self._stored)
        out.update(name=self.name_edit.text().strip(), color=text,
                   style=self.style_seg.currentData() or "solid", width=float(self.width_spin.value()),
                   mode=self.mode_seg.currentData() or "smooth", z_units=self.units_combo.currentData() or "auto",
                   in_range=self.in_range_box.isChecked(), marks=self.marks_box.isChecked(),
                   visible=self.visible_box.isChecked())
        out.update(self._source_value())
        return {k: out[k] for k in SURFACE_DEFAULTS}

    def set_value(self, data: dict) -> None:
        d = clean_surface(data) or dict(SURFACE_DEFAULTS)
        self._applying += 1
        try:
            self._stored = dict(d)
            self._set_source_value(d)
            self.name_edit.setText(d["name"])
            self._color_text = d["color"]
            self.color_btn.setColor(QColor(d["color"]))
            self.style_seg.setCurrentIndex(max(0, self.style_seg.findData(d["style"])))
            self.width_spin.setValue(d["width"])
            self.mode_seg.setCurrentIndex(max(0, self.mode_seg.findData(d["mode"])))
            self.units_combo.setCurrentIndex(max(0, self.units_combo.findData(d["z_units"])))
            self.in_range_box.setChecked(d["in_range"])
            self.marks_box.setChecked(d["marks"])
            self.visible_box.setChecked(d["visible"])
        finally:
            self._applying -= 1
        self.refresh_labels()

    def layer(self) -> Optional[QgsRasterLayer]:
        lyr = QgsProject.instance().mapLayer(self._layer_id) if self._layer_id else None
        return lyr if isinstance(lyr, QgsRasterLayer) else None

    def is_missing(self) -> bool:
        """No raster chosen, or the chosen one is no longer in the project."""
        return self.layer() is None

    def set_removing(self, on: bool) -> None:
        self._removing = bool(on)
        if not on:
            self.sync_layer()

    def sync_layer(self) -> None:
        """Show the stored layer again (after layers were removed from the project)."""
        self._applying += 1
        try:
            self._sync_layer_combo()
        finally:
            self._applying -= 1
        self.refresh_labels()

    def _sync_layer_combo(self) -> None:
        lyr = self.layer()
        self.layer_combo.setLayer(lyr)
        self.band_combo.setLayer(lyr)

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

    # ---- labels
    def refresh_labels(self) -> None:
        d = self.value()
        lyr = self.layer()
        lname = lyr.name() if lyr is not None else ""
        missing = bool(d["layer_id"]) and lyr is None
        if lyr is not None:
            name = d["name"] or lname
        elif missing:
            name = d["name"] or "Raster not in the project"
        else:
            name = d["name"] or "(choose a raster)"
        self.name_label.setText(name)
        self.name_label.setWarn(lyr is None)
        where = lname or ("layer not in the project" if missing else "no raster")
        parts = [where, f"band {d['band']}", STYLE_WORDS.get(d["style"], d["style"]), d["mode"]]
        if d["marks"]:
            parts.append("▽ marks")
        self.sub_label.setText(" · ".join(parts))
        self.name_edit.setPlaceholderText(lname or "Name in the legend")
        self.name_area.setEnabled(True)

    # ---- signals
    def _on_layer_changed(self, layer) -> None:
        if self._applying or self._removing:
            return
        self._applying += 1
        try:
            self.band_combo.setLayer(layer)
            if layer is not None and self.band_combo.currentBand() < 1:
                self.band_combo.setBand(1)
        finally:
            self._applying -= 1
        self._layer_id = layer.id() if layer is not None else ""
        self._emit()

    def _emit(self, *args) -> None:
        if self._applying:
            return
        self.refresh_labels()
        self.changed.emit()
