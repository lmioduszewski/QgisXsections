"""Reusable widgets of the XSections panel.

- Theme: the panel's colors (0.3.6: the approved panel mockup's light and dark tokens, the dark ones fixed, no longer
  the palette's highlight; ink, field and disabled still from the QGIS palette, 0.3.7 finish: but ink and disabled
  where they would not read on the dark tokens, contrast()), and panel_stylesheet(), a stylesheet whose rules are all
  scoped by objectName so that it only styles the panel's own widgets.
- CollapsibleSection (0.3.6, DESIGN.md decision 27, the three levels you can tell apart): a SectionHeader (closed: a
  solid tile; open: the navy bar; its summary chip and an amber count chip) over a SectionBody (the open section's
  framed body on a 4 px navy rail, which paints the Flare bands of its open layer cards); Subsection /
  SubsectionHeading (navy capitals with a square marker and a hairline rule, never filled); field names in plain
  sentence case (field_label).
- SegmentedControl: buttons for a short choice, with the QComboBox API the panel uses.
- field_box / pair / hrow / check_row / add_button: small labels above fields, two fields to a row, check boxes side
  by side, the dashed "+ Add layer" button.
- Disclosure (0.3.6): a round pill ("Units & datum") opening into a dashed box.
- OptionButton / OptionPopup / OptionGrid (0.3.7): a section's option buttons and the popup each opens (one at a time,
  closed by a second click, ✕, Esc or a press elsewhere); ElidedComboBox; SheetSizeCombo (the Size list: a check box
  per sheet size, an exclusive Custom).
- Verbose (0.3.6): the per-user switch (verbose(), set_verbose(), verbose_hub(); QgsSettings "xsections/verbose"),
  and Hint / Readout, the explanatory lines that show under their controls only with Verbose on.
- LayerCard (0.3.6): a layer row of Surfaces, Explorations or Other features. Closed, a small card; open, its header
  and editor are one light band joined to the section's rail (the "Flare": paint_flare, painted by the SectionBody
  that watches the card; link_cards spaces a list of them). Its check badge (CheckBadge) and its one amber problem
  line (Problem, CardInfo); RowTabs, the Layer | Depths | Water tabs of an exploration row.
- CheckCard / CardHost (0.3.6): the check card a badge opens on a click (never on hover), one per panel.
- SurfaceRow: one other surface (a raster line besides the ground) in the Surfaces list, a LayerCard with its editor.
  Its source fields (raster, band) are hooks that mf6_dialog.ModelSurfaceRow replaces for a MODFLOW 6 model surface.
- ExploSwatch / SymbolSwatch / BarSwatch / StatusDot: the header swatches of the layer rows: an exploration line in
  its look's colour (0.3.4: up to three bars for a Color row of several colours), an Other features symbol or bracket
  (0.3.6: ui.symbol_icons, the sheets' own geometry), the ground's bar; the status line's dot.
- StyleChips (0.3.4): the colours a Color row reads from its layer's QGIS style, as wrapping chips; LINE_STYLE_ICONS:
  the Sheet style grid's Solid / Dashed / Dotted icons (SegmentedControl.setItemIcon with a size).
- Small helpers the panel and the point rows share (moved from ui.dock in 0.3.3, which imports them back): _combo,
  _segmented, _narrow, _spin, _set_combo_data, _field_combo, _numeric_field_combo, _cbox, _note, _esc and set_field
  (the panel's rule for filling one field box, ui.point_guess.pick_field). 0.3.5: a number box lists number AND text
  fields (NUMBER_BOX_FILTERS: a CSV opened by OGR has only text fields), field_kind tells them apart for the guesses.
  0.3.7 finish: wrap_tip / tip_text, a long tooltip wrapped at TIP_W px.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from qgis.core import Qgis, QgsFieldProxyModel, QgsProject, QgsRasterLayer
from qgis.gui import (QgsColorButton, QgsDoubleSpinBox, QgsFieldComboBox, QgsMapLayerComboBox,
                      QgsRasterBandComboBox)
from qgis.PyQt.QtCore import (QByteArray, QEvent, QMetaType, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt,
                              QTimer, pyqtSignal, pyqtSlot)
from qgis.PyQt.QtGui import (QColor, QFont, QFontMetrics, QFontMetricsF, QIcon, QLinearGradient, QPainter,
                             QPainterPath, QPalette, QPen, QPixmap, QPolygonF)
from qgis.PyQt.QtWidgets import (QAbstractButton, QAbstractScrollArea, QAbstractSpinBox, QApplication, QBoxLayout,
                                 QCheckBox, QComboBox, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout,
                                 QLabel, QLayout, QLineEdit, QMenu, QPushButton, QScrollBar, QSizePolicy, QStyle,
                                 QStyleOptionComboBox, QStyleOptionSpinBox, QStyleOptionToolButton, QStylePainter,
                                 QToolButton, QToolTip, QVBoxLayout, QWidget)

from ..core.model import SURFACE_DEFAULTS, clean_surface
from . import settings_store
from .point_guess import pick_field
from .symbol_icons import bracket_pixmap, symbol_pixmap

try:                                   # QtSvg ships with QGIS; the icons fall back to nothing without it
    from qgis.PyQt.QtSvg import QSvgRenderer
except ImportError:                    # pragma: no cover
    QSvgRenderer = None

# sizes, px (0.3.6: the approved mockup's at the application's 12 px / Segoe UI 9 pt)
CONTROL_H = 24                         # height of fields and segmented buttons
SECTION_H = 30                         # a section header (tile or bar)
RAIL_W = 4                             # the open section's rail (its body's left border)
BODY_RADIUS = 5                        # the open body's bottom corners
CARD_RADIUS = 4                        # a closed layer card; a closed tile
SWOOP = 8                              # the Flare's concave swoops into the rail
BAND_RADIUS = 6                        # the open band's top-right and bottom-right corners
BAND_GAP = 8                           # px an open band keeps free above and below it for its swoops
SUBHEAD_H = 16                         # a subsection heading
TAB_H = 24                             # the row tabs (6 + text + 5)
BADGE_H = 18                           # the check badge
CARD_W = 272                           # the check card (narrower panels: the panel width - 8)
CARD_CLOSE_MS = 100                    # the card closes this long after the pointer left badge and card
CARD_ITEMS = 8                         # term -> value lines shown on a card block before "… and N more"
# 0.3.7 (the option buttons and their popups, the Size list; the approved mockup's rounds 6 and 8)
OPT_H = 42                             # an option button (the mockup's .opt)
OPT_GAP = 6                            # between option buttons, both ways
OPT_RADIUS = 5                         # an option button's corners
POP_RADIUS = 6                         # an option popup's corners
NOTCH_H = 7                            # the popup's notch: its apex this far above the box, touching its button's
                                       # bottom edge
NOTCH_HALF = 7                         # half the notch's width where it meets the box's top edge
POP_ROOM = 8                           # px kept free under an open popup at the bottom of the panel's content
SIZE_LIST_W = 220                      # SheetSizeCombo's open list: at least this wide (the mockup's .sizepop)
SIZE_ROW_H = 24                        # ... one sheet size row (18 px line + 3 + 3)
# The mockup's weight 500 (field names, heading links, the add button, card buttons, the main chip). Edge draws it
# with Segoe UI's Semibold face, and that is what the approved renders show; Qt's QFont.Weight.Medium finds no 500
# face and draws Regular (the stage P1 screenshots, side by side), so the panel asks for DemiBold.
MEDIUM = QFont.Weight.DemiBold
LINE_HEIGHT = 1.25                     # a layer row's name and subtitle lines, x their font size (the mockup's)


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
    bar: QColor                # open section bar, checked segment, primary button, the section rail
    bar_hover: QColor
    bar_disabled: QColor
    on_bar: QColor             # text on the bar
    heading: QColor            # subsection headings (0.3.6; closed section headers before)
    ink: QColor                # the palette's Text
    muted: QColor              # field names, hints, sub lines
    disabled: QColor
    rule: QColor               # hairline rules
    field: QColor              # field background (the palette's Base)
    field_line: QColor         # card and field borders, the tab rule
    chip: QColor               # chips of the dialogs
    chip_ink: QColor
    chip_open: QColor          # a chip on an open (bar) header
    warn: QColor               # the main chip when something is missing, warn hints
    warn_bg: QColor
    error: QColor
    link: QColor               # links, the current tab's underline
    hover: QColor
    chip_on: QColor            # checked tool button
    panel2: QColor             # inline editor background (kept)
    new: QColor                # the NEW badge's text (0.3.4; unused from 0.3.6)
    new_bg: QColor             # ... and its background
    ink2: QColor               # 0.3.6: the subtitle's label field, a hint's <b>
    chip_tile: QColor          # 0.3.6: a chip on a closed tile (its ink tile_ink)
    card_foot: QColor          # 0.3.6: the check card's footer
    ok: QColor                 # 0.3.6: the status dot
    tile: QColor               # 0.3.6: a closed section tile
    tile_hover: QColor         # 0.3.6
    tile_ink: QColor           # 0.3.6: closed tile text, caret, icon
    open_body: QColor          # 0.3.6: an open section's body
    row_rail: QColor           # 0.3.6: an open band's rail, a hovered card's border, an open pill's border
    row_open: QColor           # 0.3.6: the open band, an open pill
    band_line: QColor          # 0.3.6: the open band's 1 px outline
    pop: QColor                # 0.3.6: the check card's background
    pop_line: QColor           # 0.3.6: the check card's border, the badge's border
    amber: QColor              # 0.3.6: badges, count chips, problem lines, the card's top edge
    amber_bg: QColor           # 0.3.6
    count_open_bg: QColor      # 0.3.6: the count chip on an open bar
    count_open_ink: QColor     # 0.3.6
    field_ink: QColor          # 0.3.7 finish: text on a field (buttons, lists): ink, or with own_ink the palette's Text
                               # when it reads better on the field
    own_ink: bool = False      # 0.3.7 finish: ink is DARK_INK, not the palette's Text (too dark on the dark tokens)


_THEMES: Dict[Tuple[str, ...], Theme] = {}
# 0.3.7 finish (QGIS's Blend of Gray theme: its text #0e0e0e, its window #727272, dark enough for the dark tokens; and
# Night Mapping's disabled text #535353): below these contrasts on the dark tokens' surfaces, the palette's colour
# gives way to a fixed one
MIN_INK_CONTRAST = 4.5                 # ink on the open body and the check card (WCAG's AA for text)
MIN_DISABLED_CONTRAST = 2.5            # disabled text on the open band
DARK_INK = "#e3e9ec"                   # the mockup's dark --ink
DARK_DISABLED = "#777777"              # a dark palette's own disabled text (Qt's, the tests' night palette): 2.9:1


def _luminance(c: QColor) -> float:
    """WCAG's relative luminance of a colour (0 black to 1 white)."""
    def lin(v: int) -> float:
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c.red()) + 0.7152 * lin(c.green()) + 0.0722 * lin(c.blue())


def contrast(a: QColor, b: QColor) -> float:
    """WCAG's contrast ratio of two colours, 1 to 21 (alpha ignored)."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def theme_for(pal: QPalette) -> Theme:
    """The panel colors for a palette: the approved mockup's light tokens (navy bars) in a light theme; in a dark one
    (window lightness < 128) its dark tokens, fixed (0.3.6: QGIS Night Mapping's highlight is orange, which painted
    orange bars). In both, ink is the palette's Text, field its Base and disabled its disabled WindowText, so native
    fields match; in a dark one (0.3.7 finish) ink is DARK_INK when the palette's Text is too dark on the open body or the
    check card (own_ink: Blend of Gray; field_ink, the text on a field, stays the palette's Text when that reads
    better on its Base: Blend of Gray's dialogs, their fields #b2b2b2), and disabled DARK_DISABLED when the palette's
    is too dark on the open band."""
    cr = QPalette.ColorRole
    win, ink, base = pal.color(cr.Window), pal.color(cr.Text), pal.color(cr.Base)
    dis = pal.color(QPalette.ColorGroup.Disabled, cr.WindowText)
    key = tuple(c.name() for c in (win, ink, base, dis))
    cached = _THEMES.get(key)
    if cached is not None:
        return cached
    C = QColor
    white = C("#ffffff")
    if win.lightness() < 128:
        bar = C("#2f5a6f")
        open_body, row_open, pop = C("#172128"), C("#1c3341"), C("#1b272e")
        text = ink
        own_ink = min(contrast(ink, open_body), contrast(ink, pop)) < MIN_INK_CONTRAST
        if own_ink:
            ink = C(DARK_INK)
        field_ink = ink if contrast(ink, base) > contrast(text, base) else text
        if contrast(dis, row_open) < MIN_DISABLED_CONTRAST:
            dis = C(DARK_DISABLED)
        t = Theme(dark=True, bar=bar, bar_hover=C("#386a82"), bar_disabled=_mix(bar, win, 0.55), on_bar=white,
                  heading=C("#a9c8d8"), ink=ink, muted=C("#93a5ae"), disabled=dis, rule=C("#2d3c45"), field=base,
                  field_line=C("#3a4a53"), chip=C("#26353d"), chip_ink=C("#c3d0d6"), chip_open=C(255, 255, 255, 41),
                  warn=C("#e6b65c"), warn_bg=C("#3b2f15"), error=C("#ff8a7a"), link=C("#8fbad0"),
                  hover=C(255, 255, 255, 22), chip_on=C("#2b4250"), panel2=C("#213039"), new=C("#6fcf9a"),
                  new_bg=C("#1d3a2b"), ink2=C("#b7c4ca"), chip_tile=C(25, 51, 64, 26), card_foot=C("#1a252c"),
                  ok=C("#4ade80"), tile=C("#233038"), tile_hover=C("#2b3a44"), tile_ink=C("#d3e1e8"),
                  open_body=open_body, row_rail=C("#5aa9cf"), row_open=row_open, band_line=C("#3f6a80"),
                  pop=pop, pop_line=C("#6b5326"), amber=C("#e8b45c"), amber_bg=C("#3a2e17"),
                  count_open_bg=C(255, 214, 140, 56), count_open_ink=C("#ffe2a8"), field_ink=field_ink,
                  own_ink=own_ink)
    else:
        t = Theme(dark=False, bar=C("#193340"), bar_hover=C("#21414f"), bar_disabled=C("#9aa8b0"), on_bar=white,
                  heading=C("#193340"), ink=ink, muted=C("#5a6b74"), disabled=dis, rule=C("#d7dee2"), field=base,
                  field_line=C("#c9d2d7"), chip=C("#e3e9ec"), chip_ink=C("#4a5c65"), chip_open=C(255, 255, 255, 41),
                  warn=C("#9a6510"), warn_bg=C("#f6eedd"), error=C("#c0392b"), link=C("#446f85"),
                  hover=C(122, 146, 158, 40), chip_on=C("#dde7ed"), panel2=C("#e9eef1"), new=C("#2e7d57"),
                  new_bg=C("#e3efe8"), ink2=C("#44545d"), chip_tile=C(25, 51, 64, 26), card_foot=C("#f4f6f8"),
                  ok=C("#16a34a"), tile=C("#dbe3e8"), tile_hover=C("#cfd9df"), tile_ink=C("#193340"),
                  open_body=C("#ffffff"), row_rail=C("#3c86aa"), row_open=C("#e3eff5"), band_line=C("#8fb6ca"),
                  pop=C("#ffffff"), pop_line=C("#e7c98f"), amber=C("#b7791f"), amber_bg=C("#fbf1de"),
                  count_open_bg=C(255, 214, 140, 56), count_open_ink=C("#ffe2a8"), field_ink=ink)
    _THEMES[key] = t
    return t


def _card_button_rules(t: Theme) -> str:
    """The check card's buttons (CheckCard; also in panel_stylesheet)."""
    return f"""
QPushButton#xsCardButton {{ background: {css(t.field)}; color: {css(t.field_ink)};
    border: 1px solid {css(t.field_line)};
    border-radius: 4px; padding: 0px 10px; }}
QPushButton#xsCardButton:hover {{ border-color: {css(t.link)}; }}
QPushButton#xsCardPrimary {{ background: {css(t.bar)}; color: {css(t.on_bar)}; border: 1px solid {css(t.bar)};
    border-radius: 4px; padding: 0px 10px; }}
QPushButton#xsCardPrimary:hover {{ background: {css(t.bar_hover)}; border-color: {css(t.bar_hover)}; }}
"""


def _size_list_rules(t: Theme) -> str:
    """The Size list's box and foot line (_SizeList, its own stylesheet; also in panel_stylesheet)."""
    return f"""
QFrame#xsSizeList {{ background: {css(t.field)}; border: 1px solid {css(t.field_line)}; }}
QLabel#xsSizeFoot {{ color: {css(t.muted)}; background: palette(window); border-top: 1px solid {css(t.rule)};
    padding: 6px 10px 7px 10px; }}
"""


def _own_ink_rules(t: Theme) -> str:
    """With own_ink (0.3.7 finish, Blend of Gray: its stylesheet gives every QLabel, QCheckBox and QRadioButton its dark
    text), the panel's plain ones take ink instead (and the disabled color, on no box); else nothing. (The dock's
    only: in the dialogs they sit on QGIS's own window and fields, as dark as its text wants.)"""
    if not t.own_ink:
        return ""
    return f"""
QLabel, QCheckBox, QRadioButton {{ color: {css(t.ink)}; }}
QLabel:disabled, QCheckBox:disabled, QRadioButton:disabled {{ color: {css(t.disabled)}; background: transparent; }}
"""


def panel_stylesheet(t: Theme, plain_text: bool = False) -> str:
    """The panel's stylesheet. Every rule names an objectName, so only the panel's own widgets change; `plain_text`
    (0.3.7 finish, the dock): and _own_ink_rules. (0.3.6: the widgets painted in code (section bodies, layer cards,
    subsection headings) have no rule: a rule would fill them; the dashed boxes (xsAdd, xsMoreBody) keep a transparent
    1 px border here, their dashes painted in code. 0.3.7 finish: the :disabled rules of labels and links are on no box,
    which an application stylesheet's QWidget:disabled background would paint: Night Mapping's #323232.)"""
    return (_own_ink_rules(t) if plain_text else "") + f"""
QLabel#xsFieldLabel {{ color: {css(t.muted)}; }}
QLabel#xsFieldLabel:disabled {{ color: {css(t.disabled)}; background: transparent; }}
QLabel#xsReadout {{ color: {css(t.muted)}; border: none; border-top: 1px dashed {css(t.rule)}; padding-top: 4px; }}
QLabel#xsNote {{ color: {css(t.muted)}; }}
QLabel#xsMuted {{ color: {css(t.muted)}; }}
QLabel#xsMuted:disabled {{ color: {css(t.disabled)}; background: transparent; }}
QLabel#xsHint {{ color: {css(t.muted)}; }}
QLabel#xsHint[warn="true"] {{ color: {css(t.warn)}; }}
QLabel#xsHint[head="true"] {{ color: {css(t.link)}; }}
QLabel#xsStatus {{ color: {css(t.ink)}; }}
QToolButton#xsSegButton {{ background: {css(t.field)}; color: {css(t.field_ink)};
    border: 1px solid {css(t.field_line)};
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
QToolButton#xsTool {{ background: {css(t.field)}; color: {css(t.field_ink)}; border: 1px solid {css(t.field_line)};
    border-radius: 4px; padding: 1px 5px; }}
QToolButton#xsTool:hover {{ border-color: {css(t.link)}; }}
QToolButton#xsTool:checked {{ background: {css(t.chip_on)}; border-color: {css(t.link)}; }}
QToolButton#xsTool:disabled {{ color: {css(t.disabled)}; }}
QToolButton#xsTool::menu-indicator {{ image: none; width: 0px; }}
QToolButton#xsRowMenu {{ background: {css(t.field)}; color: {css(t.field_ink)};
    border: 1px solid {css(t.field_line)};
    border-radius: 3px; padding: 0px; }}
QToolButton#xsRowMenu:hover {{ border-color: {css(t.link)}; }}
QToolButton#xsRowMenu::menu-indicator {{ image: none; width: 0px; }}
QToolButton#xsLink {{ background: transparent; color: {css(t.link)}; border: none; padding: 0px 1px; }}
QToolButton#xsLink:hover {{ text-decoration: underline; }}
QToolButton#xsLink:disabled {{ color: {css(t.disabled)}; background: transparent; }}
QToolButton#xsAdd {{ background: transparent; color: {css(t.link)}; border: 1px solid transparent;
    border-radius: 4px; padding: 0px 6px; }}
QToolButton#xsAdd:hover {{ border-color: {css(t.link)}; }}
QToolButton#xsAdd:disabled {{ color: {css(t.disabled)}; background: transparent; }}
QPushButton#xsPrimary {{ background: {css(t.bar)}; color: {css(t.on_bar)}; border: none; border-radius: 4px;
    font-weight: 600; padding: 0px 10px; }}
QPushButton#xsPrimary:hover {{ background: {css(t.bar_hover)}; }}
QPushButton#xsPrimary:pressed {{ background: {css(t.bar.darker(115))}; }}
QPushButton#xsPrimary:disabled {{ background: {css(t.bar_disabled)}; }}
QFrame#xsSurfaceList {{ background: {css(t.field)}; border: 1px solid {css(t.field_line)}; border-radius: 3px; }}
QFrame#xsMoreBody {{ border: 1px solid transparent; border-radius: 4px; }}
QFrame#xsStyleBox {{ background: {css(t.field)}; border: 1px solid {css(t.field_line)}; border-radius: 3px; }}
QListView#xsSymbolList {{ background: {css(t.field)}; border: 1px solid {css(t.field_line)}; }}
QLabel#xsPopTitle {{ color: {css(t.ink)}; }}
QLabel#xsPopCount {{ color: {css(t.muted)}; }}
""" + _size_list_rules(t) + _card_button_rules(t)


# ---------------------------------------------------------------- section icons (monochrome, the mockup's .sico)
_SVG_HEAD = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14" fill="none">'
ICONS = {
    "line": '<path d="M1.5 11.5 5 6l3 3 4.5-6.5" stroke="currentColor" stroke-width="1.5" fill="none" '
            'stroke-linecap="round" stroke-linejoin="round"/>',
    "surfaces": '<path d="M1 4c2-1.5 4-1.5 6 0s4 1.5 6 0M1 8c2-1.5 4-1.5 6 0s4 1.5 6 0M1 12c2-1.5 4-1.5 6 0s4 1.5 6 0" '
                'stroke="currentColor" stroke-width="1.3" fill="none"/>',
    "explorations": '<path d="M7 1.5v11M4 12.5h6" stroke="currentColor" stroke-width="1.5" fill="none" '
                    'stroke-linecap="round"/><circle cx="7" cy="4" r="2.2" fill="currentColor"/>',
    "other": '<circle cx="3.5" cy="3.5" r="2" fill="currentColor"/><path d="M8 2.5c1.5 1.2 3 1.2 4.5 0" '
             'stroke="currentColor" stroke-width="1.3" fill="none"/><path d="M2 12.5V9.5h10v3" stroke="currentColor" '
             'stroke-width="1.3" fill="none"/>',
    "scale": '<rect x="1" y="4.5" width="12" height="5" rx="1" stroke="currentColor" stroke-width="1.3" fill="none"/>'
             '<path d="M4 4.5v2M7 4.5v2.8M10 4.5v2" stroke="currentColor" stroke-width="1.1"/>',
    "style": '<path d="M1 1h12v12H1z M1 5h12M1 9h12M5 1v12M9 1v12" stroke="currentColor" stroke-width="1" '
             'fill="none"/>',
}
# the Sheet style grid's line styles (0.3.4, the mockup's 22 x 8 icons), shown on icon-only segmented buttons
_LS_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 8" fill="none">{}</svg>'
LINE_STYLE_ICONS = {
    "solid": _LS_SVG.format('<path d="M1 4h20" stroke="currentColor" stroke-width="1.6"/>'),
    "dash": _LS_SVG.format('<path d="M1 4h20" stroke="currentColor" stroke-width="1.6" stroke-dasharray="5 2.5"/>'),
    "dot": _LS_SVG.format('<path d="M2 4h19" stroke="currentColor" stroke-width="1.8" stroke-dasharray="0.1 3.2" '
                          'stroke-linecap="round"/>'),
}
LINE_STYLE_ICON_SIZE = (22, 8)           # px
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


def svg_pixmap(svg: str, color: str, px: int, scale: int = 2, height: Optional[int] = None) -> QPixmap:
    """An SVG document (colours written "currentColor") drawn in `color` into a px x px pixmap (px x `height` when
    given, the document stretched to that rect: the 22 x 8 line-style icons), at `scale` x the pixels for sharp icons
    on high-dpi screens; transparent without QtSvg."""
    h = px if height is None else int(height)
    pm = QPixmap(px * scale, h * scale)
    pm.fill(Qt.GlobalColor.transparent)
    if QSvgRenderer is not None:
        r = QSvgRenderer(QByteArray(svg.replace("currentColor", color).encode("utf-8")))
        if r.isValid():
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            r.render(p, QRectF(0.0, 0.0, px * scale, h * scale))
            p.end()
    pm.setDevicePixelRatio(scale)
    return pm


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


def _px_font(base: QFont, px: float, weight: Optional[QFont.Weight] = None, spacing: float = 0.0) -> QFont:
    """The mockup's `px` (at the application's 12 px font), following the app font: _scaled_font by px / 12."""
    return _scaled_font(base, px / 12.0, weight, spacing)


def _corner_path(r: QRectF, tl: Any = 0.0, tr: Any = 0.0, br: Any = 0.0, bl: Any = 0.0) -> QPainterPath:
    """`r` with its own radius at each corner (a number, or (rx, ry) for an elliptical corner; 0: square)."""
    def radii(v):
        return (float(v), float(v)) if isinstance(v, (int, float)) else (float(v[0]), float(v[1]))
    (tlx, tly), (trx, try_), (brx, bry), (blx, bly) = (radii(v) for v in (tl, tr, br, bl))
    x0, y0, x1, y1 = r.left(), r.top(), r.right(), r.bottom()
    path = QPainterPath(QPointF(x0 + tlx, y0))
    path.lineTo(x1 - trx, y0)
    if trx > 0 and try_ > 0:
        path.arcTo(QRectF(x1 - 2 * trx, y0, 2 * trx, 2 * try_), 90, -90)
    path.lineTo(x1, y1 - bry)
    if brx > 0 and bry > 0:
        path.arcTo(QRectF(x1 - 2 * brx, y1 - 2 * bry, 2 * brx, 2 * bry), 0, -90)
    path.lineTo(x0 + blx, y1)
    if blx > 0 and bly > 0:
        path.arcTo(QRectF(x0, y1 - 2 * bly, 2 * blx, 2 * bly), 270, -90)
    path.lineTo(x0, y0 + tly)
    if tlx > 0 and tly > 0:
        path.arcTo(QRectF(x0, y0, 2 * tlx, 2 * tly), 180, -90)
    path.closeSubpath()
    return path


def _triangle(x: float, top: float, w: float, h: float) -> QPolygonF:
    """An upward triangle `w` wide and `h` tall with its top-left corner of the box at (x, top) (the warn marks)."""
    return QPolygonF([QPointF(x, top + h), QPointF(x + w / 2.0, top), QPointF(x + w, top + h)])


# ---------------------------------------------------------------- collapsible section
class SectionHeader(QWidget):
    """Clickable header (0.3.6): caret, icon, UPPERCASE title, and at the right an amber count chip (problems(): the
    section's layers that need a look; 0 hides it) after the summary chip (amber with a dot when something is missing).
    Closed: a solid rounded tile; open: the navy bar, its top corners rounded, sitting on the section's body.
    (`first` / `last` are kept for the dock; they no longer draw rules.)"""

    clicked = pyqtSignal()
    HEIGHT = SECTION_H
    PAD = 9.0                          # px from either edge
    CARET_X = 7.5                      # the caret's box (7 px wide open), then 6 + 7 px to the icon (the mockup's)
    ICON_X = 20.5
    ICON = 14.0
    TITLE_X = ICON_X + ICON + 7.0
    CHIP_H = 15.0                      # the summary chip: 10.5 px text on a 1.25 line + 1 px padding (the mockup's)
    COUNT_GAP = 11.0                   # summary chip to count chip: the flex gap 7 + its margin 4 (the mockup's)

    def __init__(self, title: str, icon: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsSectionHeader")
        self._title = title
        self._icon = icon
        self._chip = ""
        self._warn = False
        self._open = False
        self._hover = False
        self._problems = 0
        self._problems_tip = ""
        self.first = False
        self.last = False
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

    def setProblems(self, n: int, tip: str = "") -> None:
        """The count chip: `n` layers that need a look (0 hides it); `tip` its tooltip (also the header's)."""
        n = max(0, int(n))
        if (n, tip) == (self._problems, self._problems_tip):
            return
        self._problems, self._problems_tip = n, str(tip)
        self._sync_accessible()
        self.update()

    def problems(self) -> int:
        return self._problems

    def isOpen(self) -> bool:
        return self._open

    def setOpen(self, on: bool) -> None:
        self._open = bool(on)
        self._sync_accessible()
        self.update()

    def _sync_accessible(self) -> None:
        state = "open" if self._open else "closed"
        tip = self._problems_tip if self._problems else ""
        self.setAccessibleName(f"{self._title} ({state})" + (f": {self._chip}" if self._chip else "")
                               + (f"; {tip}" if tip else ""))
        self.setToolTip("\n".join(x for x in (self._chip, tip) if x))

    # ---- size
    def sizeHint(self) -> QSize:
        return QSize(220, self.HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return QSize(60, self.HEIGHT)

    def _title_font(self) -> QFont:
        return _px_font(self.font(), 11.5, QFont.Weight.Bold, 4.5)

    def _chip_font(self) -> QFont:
        return _px_font(self.font(), 10.5, QFont.Weight.DemiBold if self._warn else MEDIUM)

    def _count_font(self) -> QFont:
        return _px_font(self.font(), 10.0, QFont.Weight.Bold)

    def parts(self) -> Dict[str, Any]:
        """Where everything goes at the current size (paintEvent and tests): the title as drawn and its rect, the
        chip's rect and text as drawn (None / "" when there is no room or no chip), the count chip's rect (None)."""
        w, h = float(self.width()), float(self.height())
        cy = h / 2.0
        x = self.TITLE_X if (QSvgRenderer is not None and self._icon in ICONS) else self.ICON_X
        right = w - self.PAD
        count_rect = None
        if self._problems > 0:
            fm = QFontMetricsF(self._count_font())
            cw = 6.0 + 7.0 + 3.0 + fm.horizontalAdvance(str(self._problems)) + 6.0
            count_rect = QRectF(right - cw, cy - 8.0, cw, 16.0)
            right = count_rect.left() - self.COUNT_GAP
        tf = self._title_font()
        fm = QFontMetrics(tf)
        room = right - x - (44.0 if self._chip else 0.0)
        title = fm.elidedText(self._title.upper(), Qt.TextElideMode.ElideRight, int(max(0.0, room)))
        tw = float(fm.horizontalAdvance(title))
        title_rect = QRectF(x, 0.0, tw + 4.0, h)
        chip_rect, chip_text = None, ""
        if self._chip:
            cfm = QFontMetrics(self._chip_font())
            pad, dot = 7.0, (11.0 if self._warn else 0.0)
            start = x + tw + 10.0
            natural = cfm.horizontalAdvance(self._chip) + 2 * pad + dot
            cw = min(natural, right - start)
            if cw >= 24.0:
                chip_text = cfm.elidedText(self._chip, Qt.TextElideMode.ElideRight, int(cw - 2 * pad - dot))
                ch = float(min(self.CHIP_H, h - 8))
                chip_rect = QRectF(right - cw, cy - ch / 2.0, cw, ch)
        return dict(title=title, title_rect=title_rect, chip=chip_rect, chip_text=chip_text, count=count_rect)

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
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        r = QRectF(0.0, 0.0, w, h)
        if self._open:
            p.fillPath(_corner_path(r, CARD_RADIUS, CARD_RADIUS, 0, 0), t.bar_hover if self._hover else t.bar)
            fg = t.on_bar
        else:
            p.fillPath(_corner_path(r, CARD_RADIUS, CARD_RADIUS, CARD_RADIUS, CARD_RADIUS),
                       t.tile_hover if self._hover else t.tile)
            fg = t.tile_ink
        cy = h / 2.0
        x = self.CARET_X
        # caret (closed at 80 %, the mockup's .caret)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fg)
        if self._open:
            tri = [QPointF(x, cy - 2.0), QPointF(x + 7.0, cy - 2.0), QPointF(x + 3.5, cy + 2.5)]
        else:
            p.setOpacity(0.8)
            tri = [QPointF(x + 1.5, cy - 3.5), QPointF(x + 6.0, cy), QPointF(x + 1.5, cy + 3.5)]
        p.drawPolygon(QPolygonF(tri))
        p.setOpacity(1.0)
        # icon (at 85 %, the mockup's .sico)
        rend = _icon_renderer(self._icon, fg.name())
        if rend is not None:
            p.setOpacity(0.85)
            rend.render(p, QRectF(self.ICON_X, cy - self.ICON / 2.0, self.ICON, self.ICON))
            p.setOpacity(1.0)
        parts = self.parts()
        p.setFont(self._title_font())
        p.setPen(fg)
        p.drawText(parts["title_rect"], int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                   parts["title"])
        rect = parts["chip"]
        if rect is not None:
            if self._warn:
                bg, ink = t.warn_bg, t.warn
            elif self._open:
                bg, ink = t.chip_open, t.on_bar
            else:
                bg, ink = t.chip_tile, t.tile_ink
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(rect, rect.height() / 2.0, rect.height() / 2.0)
            tx = rect.left() + 7.0
            if self._warn:
                p.setBrush(ink)
                p.drawEllipse(QPointF(tx + 3.0, cy), 3.0, 3.0)
                tx += 11.0
            p.setFont(self._chip_font())
            p.setPen(ink)
            p.drawText(QRectF(tx, rect.top(), rect.right() - 7.0 - tx + 2.0, rect.height()),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), parts["chip_text"])
        rect = parts["count"]
        if rect is not None:
            bg, ink = (t.count_open_bg, t.count_open_ink) if self._open else (t.amber_bg, t.amber)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(rect, 8.0, 8.0)
            p.setBrush(ink)
            p.drawPolygon(_triangle(rect.left() + 6.0, cy - 3.0, 7.0, 6.0))
            p.setFont(self._count_font())
            p.setPen(ink)
            p.drawText(QRectF(rect.left() + 16.0, rect.top(), rect.width() - 16.0, rect.height()),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), str(self._problems))
        if self.hasFocus():
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            p.setPen(QPen(fg, 1, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.rect().adjusted(2, 2, -3, -3))
        p.end()


class SectionBody(QFrame):
    """An open section's framed body (0.3.6): a 4 px navy rail on the left, 1 px navy right and bottom borders (the
    bar is above it), rounded bottom corners, the open-body colour inside. It hosts the Flare bands: every watched
    LayerCard (watch) that is shown with its editor open is painted here as one light band from the rail to the card's
    right edge (paint_flare); the card itself paints nothing then. The body repaints whenever a watched card or one of
    its ancestors below the body moves, resizes, shows or hides, and on the card's editorToggled."""

    MARGINS = (13, 10, 11, 13)         # rail 4 + 9; 10; 1 + 10; 1 + 12
    SPACING = 8

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsSectionBody")
        self._cards: List[QWidget] = []
        self.body_layout = QVBoxLayout(self)
        self.body_layout.setContentsMargins(*self.MARGINS)
        self.body_layout.setSpacing(self.SPACING)

    # ---- watched cards
    def watch(self, w: QWidget) -> None:
        """Paint `w`'s band (a LayerCard descendant) while it is open."""
        if not any(c is w for c in self._cards):
            self._cards.append(w)
            sig = getattr(w, "editorToggled", None)
            if sig is not None:
                sig.connect(self._on_card_toggled)
        self._hook(w)
        self.update()

    def unwatch(self, w: QWidget) -> None:
        self._cards = [c for c in self._cards if c is not w]
        try:
            w.removeEventFilter(self)
            w.editorToggled.disconnect(self._on_card_toggled)
        except (RuntimeError, TypeError, AttributeError):
            pass
        self.update()

    def watched(self) -> List[QWidget]:
        out = []
        for c in self._cards:
            try:
                c.objectName()
            except RuntimeError:
                continue
            out.append(c)
        self._cards = out
        return list(out)

    def _hook(self, w: QWidget) -> None:
        """The event filter on `w` and, when it is inside this body, on each of its ancestors below the body (a list
        that moves moves its cards without a Move event of theirs)."""
        w.installEventFilter(self)
        if not self.isAncestorOf(w):
            return
        x = w.parentWidget()
        while x is not None and x is not self:
            x.installEventFilter(self)
            x = x.parentWidget()

    def _on_card_toggled(self, *_args) -> None:
        self.update()

    def eventFilter(self, obj, ev) -> bool:
        et = ev.type()
        if et in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide):
            self.update()
        elif et == QEvent.Type.ParentChange:
            if any(c is obj for c in self._cards):
                self._hook(obj)
            self.update()
        return False

    def bands(self) -> List[Tuple[int, int, int, Optional[int]]]:
        """(T, B, R, rule_y) of each band to paint, in this body's coordinates, top to bottom."""
        out = []
        for c in self.watched():
            try:
                if not c.isVisible() or not c.editor_open() or not self.isAncestorOf(c):
                    continue
                rect = c.band_rect()
                tl = c.mapTo(self, rect.topLeft())
                ry = c.rule_y()
                rule = c.mapTo(self, QPoint(0, ry)).y() if ry is not None else None
            except RuntimeError:
                continue
            out.append((tl.y(), tl.y() + rect.height(), tl.x() + rect.width(), rule))
        return sorted(out, key=lambda b: b[0])

    def paintEvent(self, _e) -> None:
        t = theme_for(self.palette())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillPath(_corner_path(QRectF(self.rect()), 0, 0, BODY_RADIUS, BODY_RADIUS), t.bar)
        inner = QRectF(self.rect().adjusted(RAIL_W, 0, -1, -1))
        p.fillPath(_corner_path(inner, 0, 0, BODY_RADIUS - 1, 1), t.open_body)
        for top, bottom, right, rule in self.bands():
            paint_flare(p, t, RAIL_W, top, bottom, right, rule)
        p.end()


class CollapsibleSection(QWidget):
    """A section of the panel: SectionHeader over a SectionBody. Collapsed when created. setCollapsed / isCollapsed
    follow QgsCollapsibleGroupBox. Its bottom margin spaces the sections (0.3.6): 3 px under a closed tile, 10 px
    under an open section (one card: the bar and its body)."""

    collapsedStateChanged = pyqtSignal(bool)
    GAP_CLOSED, GAP_OPEN = 3, 10

    def __init__(self, title: str, icon: str = "", object_name: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        self.header = SectionHeader(title, icon, self)
        self.body = SectionBody(self)
        self.body_layout = self.body.body_layout
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, self.GAP_CLOSED)
        self._lay.setSpacing(0)
        self._lay.addWidget(self.header)
        self._lay.addWidget(self.body)
        self._collapsed = True
        self.body.hide()
        self.header.clicked.connect(self.toggle)

    def addWidget(self, w: QWidget) -> QWidget:
        self.body_layout.addWidget(w)
        return w

    def add_subsection(self, title: str, right: Sequence[QWidget] = ()) -> "Subsection":
        """A Subsection added to the body (the first thing in the body gets no top margin)."""
        sub = Subsection(title, right)
        sub.set_first(self.body_layout.count() == 0)
        self.body_layout.addWidget(sub)
        return sub

    def title(self) -> str:
        return self.header.title()

    def isCollapsed(self) -> bool:
        return self._collapsed

    def setCollapsed(self, collapsed: bool) -> None:
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._lay.setContentsMargins(0, 0, 0, self.GAP_CLOSED if collapsed else self.GAP_OPEN)
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

    def setProblems(self, n: int, tip: str = "") -> None:
        self.header.setProblems(n, tip)

    def problems(self) -> int:
        return self.header.problems()


# ---------------------------------------------------------------- subsections (0.3.6)
class _HeadTitle(QWidget):
    """A subsection heading's 6 px square marker and its UPPERCASE title, painted (never filled)."""

    MARK, GAP = 6.0, 8.0

    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._title = title
        self.setFont(_px_font(self.font(), 10.5, QFont.Weight.Bold, 8.0))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(SUBHEAD_H)

    def text(self) -> str:
        return self._title.upper()

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        return QSize(int(self.MARK + self.GAP) + fm.horizontalAdvance(self.text()) + 2, SUBHEAD_H)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        if e.type() == QEvent.Type.FontChange:
            self.updateGeometry()

    def paintEvent(self, _e) -> None:
        t = theme_for(self.palette())
        color = t.heading if self.isEnabled() else t.disabled
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cy = self.height() / 2.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(0.0, cy - self.MARK / 2.0, self.MARK, self.MARK), 1.0, 1.0)
        p.setPen(color)
        p.setFont(self.font())
        p.drawText(QRectF(self.MARK + self.GAP, 0.0, self.width() - self.MARK - self.GAP, self.height()),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())
        p.end()


class _Rule(QWidget):
    """A 1 px hairline in the theme's rule colour: across a widget 1 px high, or through the middle of a taller one
    (a subsection heading's rule)."""

    def __init__(self, height: int = 1, parent: Optional[QWidget] = None, color: str = "rule"):
        super().__init__(parent)
        self._color = color
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)

    def sizeHint(self) -> QSize:
        return QSize(0, self.height())

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(QRect(0, (self.height() - 1) // 2, self.width(), 1), getattr(theme_for(self.palette()),
                                                                                 self._color))
        p.end()


class SubsectionHeading(QWidget):
    """A subsection's heading (0.3.6, D2): a 6 px square marker, the UPPERCASE title in the heading colour, a 1 px
    rule filling the rest, then the `right` widgets (links, head hints). Never filled, no hover, not clickable."""

    def __init__(self, title: str, right: Sequence[QWidget] = (), parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsSubheading")
        self._title = title
        self.setAccessibleName(title)
        self.setFixedHeight(SUBHEAD_H)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(8)
        self.label = _HeadTitle(title, self)
        self.rule = _Rule(SUBHEAD_H, self)
        self._lay.addWidget(self.label, 0, Qt.AlignmentFlag.AlignVCenter)
        self._lay.addWidget(self.rule, 1, Qt.AlignmentFlag.AlignVCenter)
        for w in right:
            self.addRight(w)

    def title(self) -> str:
        return self._title

    def addRight(self, w: QWidget) -> QWidget:
        w.setMaximumHeight(SUBHEAD_H)
        self._lay.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        return w


class Subsection(QWidget):
    """A subsection of a section's body (0.3.6): its SubsectionHeading over its widgets (body_layout, spacing 8). Not
    the first thing in its body, it keeps 12 px above its heading (20 px with the body's spacing, the mockup's)."""

    TOP = 12

    def __init__(self, title: str, right: Sequence[QWidget] = (), parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.heading = SubsectionHeading(title, right, self)
        self.body_layout = QVBoxLayout(self)
        self.body_layout.setContentsMargins(0, self.TOP, 0, 0)
        self.body_layout.setSpacing(8)
        self.body_layout.addWidget(self.heading)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def addWidget(self, w: QWidget) -> QWidget:
        self.body_layout.addWidget(w)
        return w

    def title(self) -> str:
        return self.heading.title()

    def set_first(self, on: bool) -> None:
        self.body_layout.setContentsMargins(0, 0 if on else self.TOP, 0, 0)


# ---------------------------------------------------------------- segmented control
class SegmentedControl(QWidget):
    """Buttons side by side for a short choice, with the QComboBox API the panel uses: addItem(text, data),
    count, itemText, itemData, findData, findText, currentIndex, setCurrentIndex, currentData, currentText,
    and the signals currentIndexChanged(int) (also for programmatic changes) and activated(int) (clicks).
    setItemShortText gives a button a shorter text, shown while the full texts do not all fit; setItemIcon makes a
    button show only an icon (the text stays its accessible name)."""

    currentIndexChanged = pyqtSignal(int)
    activated = pyqtSignal(int)
    ICON_PX = 12                           # icon-only buttons (setItemIcon)

    def __init__(self, items: Sequence[Tuple[str, Any]] = (), parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsSegmented")
        self._texts: List[str] = []
        self._short: List[str] = []
        self._data: List[Any] = []
        self._icons: List[Any] = []        # None, a QIcon, or an SVG document drawn in the theme's colours
        self._icon_sizes: List[QSize] = []  # each button's icon size (setItemIcon; ICON_PX square by default)
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
        self._icons.append(None)
        self._icon_sizes.append(QSize(self.ICON_PX, self.ICON_PX))
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
        self._texts, self._short, self._data, self._icons, self._buttons = [], [], [], [], []
        self._icon_sizes = []
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

    def setItemIcon(self, i: int, icon: Any, size: Optional[QSize] = None) -> None:
        """Button `i` shows only `icon` (its text stays the accessible name; give it a tooltip too). `icon` is a
        QIcon, or an SVG document whose colours are "currentColor": drawn in the ink colour, and in the on-bar colour
        while the button is checked (redrawn when the palette changes). `size`: the icon's size (default ICON_PX
        square; the line-style icons are 22 x 8)."""
        if not 0 <= i < len(self._buttons):
            return
        self._icons[i] = icon
        self._icon_sizes[i] = QSize(size) if size is not None else QSize(self.ICON_PX, self.ICON_PX)
        b = self._buttons[i]
        b.setAccessibleName(self._texts[i])
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        b.setIconSize(self._icon_sizes[i])
        self._apply_icon(i)

    def itemIcon(self, i: int) -> Any:
        return self._icons[i] if 0 <= i < len(self._icons) else None

    def itemIconSize(self, i: int) -> QSize:
        return QSize(self._icon_sizes[i]) if 0 <= i < len(self._icon_sizes) else QSize(self.ICON_PX, self.ICON_PX)

    def _apply_icon(self, i: int) -> None:
        icon = self._icons[i]
        if icon is None:
            return
        size = self._icon_sizes[i]
        if isinstance(icon, str):
            t = theme_for(self.palette())
            q = QIcon()
            for color, mode, state in ((t.field_ink, QIcon.Mode.Normal, QIcon.State.Off),
                                       (t.field_ink, QIcon.Mode.Active, QIcon.State.Off),
                                       (t.on_bar, QIcon.Mode.Normal, QIcon.State.On),
                                       (t.on_bar, QIcon.Mode.Active, QIcon.State.On),
                                       (t.disabled, QIcon.Mode.Disabled, QIcon.State.Off),
                                       (t.field, QIcon.Mode.Disabled, QIcon.State.On)):
                q.addPixmap(svg_pixmap(icon, color.name(), size.width(), height=size.height()), mode, state)
            icon = q
        self._buttons[i].setIconSize(size)
        self._buttons[i].setIcon(icon)

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        if e.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            for i, icon in enumerate(self._icons):
                if isinstance(icon, str):
                    self._apply_icon(i)

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

    TEXT_PAD = 6                           # px a button needs beside its text (its borders and padding)

    def neededWidth(self) -> int:
        """The width at which no button cuts its text (its short text when it has one; an icon button its icon): the
        buttons share the width equally (0.3.6: pair() stacks its two fields when a column is narrower)."""
        if not self._buttons:
            return 0
        fm = QFontMetrics(self._buttons[0].font())
        each = 0
        for text, short, icon, size in zip(self._texts, self._short, self._icons, self._icon_sizes):
            need = size.width() if icon is not None else fm.horizontalAdvance(short or text)
            each = max(each, need + self.TEXT_PAD)
        return each * len(self._buttons)


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
    """The small muted label above a field, in plain sentence case as given (0.3.6, D2: no more capitals)."""
    lab = QLabel(text)
    lab.setObjectName("xsFieldLabel")
    lab.setFont(_px_font(lab.font(), 11.0, MEDIUM))
    lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    lab.setToolTip(text)
    return lab


def note_label(text: str) -> QLabel:
    """A small muted note in a field's label line ("all layers", "plotted / in the layer")."""
    lab = QLabel(text)
    lab.setObjectName("xsMuted")
    lab.setFont(_scaled_font(lab.font(), 0.84, QFont.Weight.DemiBold))
    lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    return lab


def field_box(label: str, widget: QWidget, links: Sequence[QWidget] = (), note: str = "", tip: str = "") -> QWidget:
    """`widget` under its label; `links` (small link buttons) sit at the right of the label line, `note` (muted)
    right after the label. `tip` (0.3.6): the label's tooltip instead of its text (where an explanation that left the
    panel goes for a segmented control, whose buttons carry tooltips of their own)."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    lab = None
    if links or note:
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(3)
        lab = field_label(label)
        if note:
            lab.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            head.addWidget(lab, 0)
            n = note_label(note)
            w.note = n
            head.addWidget(n, 1)
        else:
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
        if tip:
            lab.setToolTip(tip)
    w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    return w


def _spin_needed(s: QAbstractSpinBox) -> int:
    """The width a spin box needs to show its number uncut: its buttons and frame (what the style leaves of a box for
    the text), the text, and the line edit's 2 px margins (its own size hint is for the widest of its whole range)."""
    opt = QStyleOptionSpinBox()
    s.initStyleOption(opt)
    opt.rect = QRect(0, 0, 1000, max(s.height(), CONTROL_H))
    edit = s.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, opt, QStyle.SubControl.SC_SpinBoxEditField, s)
    line = s.findChild(QLineEdit)          # (lineEdit() is protected)
    m = line.textMargins() if line is not None else None
    pad = 4 + (m.left() + m.right() if m is not None else 0)
    return 1000 - edit.width() + s.fontMetrics().horizontalAdvance(s.text()) + pad


def _needed_width(w: QWidget) -> int:
    """The width `w` needs to show what it holds uncut (0.3.6, pair()): segmented buttons' texts, spin boxes' numbers,
    check boxes' texts, and in a row of widgets each one's own minimum; 0 for what elides (labels, combo boxes)."""
    if isinstance(w, SegmentedControl):
        return w.neededWidth()
    if isinstance(w, QAbstractSpinBox):
        return _spin_needed(w)
    if isinstance(w, QCheckBox):
        return w.sizeHint().width()
    lay = w.layout()
    return _layout_needed(lay) if lay is not None else 0


def _layout_needed(lay: QLayout) -> int:
    m = lay.contentsMargins()
    parts: List[Tuple[int, int, int]] = []               # (needed, column, column span) of each shown item
    for i in range(lay.count()):
        it = lay.itemAt(i)
        if it.isEmpty():
            continue
        x, sub = it.widget(), it.layout()
        need = it.minimumSize().width()                  # (0 for an Ignored widget)
        if x is not None:
            need = max(need, _needed_width(x))
        elif sub is not None:
            need = max(need, _layout_needed(sub))
        col, span = 0, 1
        if isinstance(lay, QGridLayout):
            _r, col, _rs, span = lay.getItemPosition(i)
        parts.append((need, col, span))
    if not parts:
        return 0
    if isinstance(lay, QBoxLayout) and lay.direction() in (QBoxLayout.Direction.LeftToRight,
                                                           QBoxLayout.Direction.RightToLeft):
        need = sum(n for n, _c, _s in parts) + max(0, lay.spacing()) * (len(parts) - 1)
    elif isinstance(lay, QGridLayout):
        cols: Dict[int, int] = {}
        for n, c, span in parts:
            if span == 1:
                cols[c] = max(cols.get(c, 0), n, lay.columnMinimumWidth(c))
        need = sum(cols.values()) + max(0, lay.horizontalSpacing()) * (len(cols) - 1)
        need = max([need] + [n for n, _c, span in parts if span != 1])
    else:
        need = max(n for n, _c, _s in parts)
    return need + m.left() + m.right()


class _Pair(QWidget):
    """pair()'s two fields: side by side, sharing the width by their stretch, bottoms aligned; one over the other
    while a column would be narrower than what it holds needs (0.3.6: the 260 px dock, _needed_width: segmented
    buttons' texts, spin boxes' numbers). Checked again on a resize, a show, a layout request and a number typed."""

    SPACING = 8

    def __init__(self, left: Optional[QWidget], right: Optional[QWidget], stretch: Tuple[int, int]):
        super().__init__()
        self._stretch = (int(stretch[0]), int(stretch[1]))
        self._stacked = False
        self._filler: Optional[QWidget] = None             # the empty right column of pair(field, None)
        self._lay = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(self.SPACING)
        self._cols: List[QWidget] = []
        for x, st in ((left, stretch[0]), (right, stretch[1])):
            if x is None:
                x = self._filler = QWidget()
            x.setSizePolicy(QSizePolicy.Policy.Ignored, x.sizePolicy().verticalPolicy())
            self._lay.addWidget(x, st, Qt.AlignmentFlag.AlignBottom)
            self._cols.append(x)
        for s in self.findChildren(QAbstractSpinBox):
            changed = getattr(s, "textChanged", None)  # (QSpinBox, QDoubleSpinBox: also for a value set in code)
            if changed is not None:
                changed.connect(self._reflow)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def stacked(self) -> bool:
        """The two fields are one over the other (the panel is too narrow for them side by side)."""
        return self._stacked

    def _reflow(self, *_args) -> None:
        if not self.isVisible():           # (a hidden pair has no width yet; its show checks again)
            return
        total = max(1, sum(self._stretch))
        room = max(0, self.width() - self.SPACING)
        stack = any(_needed_width(x) > room * st / total
                    for x, st in zip(self._cols, self._stretch) if x is not self._filler)
        if stack == self._stacked:
            return
        self._stacked = stack
        self._lay.setDirection(QBoxLayout.Direction.TopToBottom if stack else QBoxLayout.Direction.LeftToRight)
        for i, st in enumerate(self._stretch):
            self._lay.setStretch(i, 0 if stack else st)
        if self._filler is not None:
            self._filler.setVisible(not stack)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._reflow()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._reflow()

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.LayoutRequest:      # (a field shown or hidden in a column)
            self._reflow()
        return super().event(e)


def pair(left: Optional[QWidget], right: Optional[QWidget], stretch: Tuple[int, int] = (1, 1)) -> QWidget:
    """Two fields side by side, sharing the width by `stretch` (equal halves by default), bottoms aligned; one over
    the other while the panel is too narrow for what they hold (0.3.6, _Pair)."""
    return _Pair(left, right, stretch)


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


class _CheckGrid(QWidget):
    """checkbox_grid()'s check boxes in `columns` equal columns; in one column while a column is narrower than the
    widest box's text (0.3.6: the 260 px dock; a check box's text is never cut). Checked again on a resize and a
    show."""

    SPACING = 8

    def __init__(self, boxes: Sequence[QWidget], columns: int):
        super().__init__()
        self._boxes = list(boxes)
        self._columns = max(1, int(columns))
        self._shown = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(self.SPACING)
        self._grid.setVerticalSpacing(4)
        for b in self._boxes:
            b.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._place(self._columns)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def columns(self) -> int:
        """The columns the boxes are in now (`columns`, or 1 while the panel is too narrow)."""
        return self._shown

    def _place(self, n: int) -> None:
        if n == self._shown:
            return
        self._shown = n
        for b in self._boxes:
            self._grid.removeWidget(b)
        for i, b in enumerate(self._boxes):
            self._grid.addWidget(b, i // n, i % n)
        for c in range(self._columns):
            self._grid.setColumnStretch(c, 1 if c < n else 0)

    def _reflow(self) -> None:
        if not self.isVisible():
            return
        room = (self.width() - self.SPACING * (self._columns - 1)) / self._columns
        need = max([b.sizeHint().width() for b in self._boxes if not b.isHidden()] or [0])
        self._place(self._columns if need <= room else 1)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._reflow()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._reflow()


def checkbox_grid(boxes: Sequence[QWidget], columns: int = 2) -> QWidget:
    """Check boxes in `columns` equal columns, row by row; one column while the panel is too narrow (_CheckGrid)."""
    return _CheckGrid(boxes, columns)


def link_button(text: str, tooltip: str = "") -> QToolButton:
    b = QToolButton()
    b.setObjectName("xsLink")
    b.setText(text)
    b.setToolTip(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setAutoRaise(True)
    b.setFont(_scaled_font(b.font(), 0.9))
    return b


def check_row(*boxes: QWidget) -> QWidget:
    """Check boxes side by side, 16 px apart, at the left (0.3.6, the mockup's cbrow)."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(16)
    for b in boxes:
        lay.addWidget(b, 0)
    lay.addStretch(1)
    w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    return w


DASH = (3.0, 2.0)                      # a dashed box's dashes and gaps, px (the mockup's 1 px CSS dashed border)


def paint_dashed_box(w: QWidget, color: QColor, radius: float = 4.0) -> None:
    """A 1 px dashed rounded border round `w` (0.3.6): drawn here because a stylesheet's dashed border comes out a
    faint dotted hairline (Qt draws it 1 device px wide, dot by dot); the stylesheet keeps a transparent 1 px border
    in its place, so the contents sit where they did."""
    p = QPainter(w)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color, 1.0)                 # (1 px wide at any screen scale: not cosmetic)
    pen.setCosmetic(False)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    pen.setDashPattern(list(DASH))
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(w.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    p.end()


class _AddButton(QToolButton):
    """add_button(): dashed in field_line; on hover the stylesheet's solid link-coloured border instead."""

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        opt = QStyleOptionToolButton()
        self.initStyleOption(opt)
        if not (self.isEnabled() and opt.state & QStyle.StateFlag.State_MouseOver):
            # (the theme from the parent's palette: the stylesheet's transparent background is in the button's own)
            paint_dashed_box(self, theme_for((self.parentWidget() or self).palette()).field_line)


def add_button(text: str, tip: str = "") -> QToolButton:
    """The full-width dashed "+ Add layer" button (0.3.6, the mockup's .addb)."""
    b = _AddButton()
    b.setObjectName("xsAdd")
    b.setText(text)
    b.setToolTip(tip)
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    b.setFixedHeight(CONTROL_H)
    b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    b.setFont(_px_font(b.font(), 11.5, MEDIUM))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class ElidedLabel(QWidget):
    """One line of text, elided at the right (or `elide`: in the middle, for a file path) when there is no room.
    `small`: the muted sub-line style (10.5 px); `warn`: amber (a missing layer); 0.3.6: setAmber (the badge's amber:
    a row's problem line) and setKeyPart (one run of the text in ink2: a subtitle's label field)."""

    def __init__(self, text: str = "", small: bool = False, parent: Optional[QWidget] = None,
                 elide: Qt.TextElideMode = Qt.TextElideMode.ElideRight):
        super().__init__(parent)
        self._text = text
        self._small = small
        self._warn = False
        self._amber = False
        self._bold = False
        self._muted = False
        self._key = ""
        self._line: Optional[float] = None
        self._elide = elide
        if small:
            self.setFont(_px_font(self.font(), 10.5))
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._fit_height()

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

    def setAmber(self, on: bool) -> None:
        """The amber of the check badges (a row's problem line); before warn."""
        if bool(on) != self._amber:
            self._amber = bool(on)
            self.update()

    def isAmber(self) -> bool:
        return self._amber

    def setMuted(self, muted: bool) -> None:
        """The muted color without the small font (e.g. a placeholder)."""
        if bool(muted) != self._muted:
            self._muted = bool(muted)
            self.update()

    def setBold(self, bold: bool) -> None:
        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
        self.setFont(f)

    def setKeyPart(self, text: str) -> None:
        """The first occurrence of `text` in the drawn (elided) string is painted in ink2 ("" none)."""
        if str(text or "") != self._key:
            self._key = str(text or "")
            self.update()

    def keyPart(self) -> str:
        return self._key

    def setLineHeight(self, factor: Optional[float]) -> None:
        """The line's height as `factor` x the font size (0.3.6: a layer row's name area, the mockup's CSS line
        height); None: the font's own height + 1 (as before)."""
        self._line = factor
        self._fit_height()

    def _line_h(self) -> int:
        if self._line:
            f = self.font()
            em = f.pointSizeF() * self.logicalDpiY() / 72.0 if f.pointSizeF() > 0 else float(f.pixelSize())
            return max(1, int(round(em * self._line)))
        return QFontMetrics(self.font()).height() + 1

    def _fit_height(self) -> None:
        self.setFixedHeight(self._line_h())

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self._text) + 2, self._line_h())

    def minimumSizeHint(self) -> QSize:
        return QSize(12, self._line_h())

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        if e.type() == QEvent.Type.FontChange:
            self._fit_height()

    def paintEvent(self, _e) -> None:
        t = theme_for(self.palette())
        p = QPainter(self)
        if self._amber:
            color = t.amber
        elif self._warn:
            color = t.warn
        elif self._small or self._muted:
            color = t.muted
        elif not self.isEnabled():
            color = t.disabled
        else:
            color = t.ink                  # (the palette's Text, but under own_ink)
        p.setFont(self.font())
        flags = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        text = QFontMetrics(self.font()).elidedText(self._text, self._elide, self.width())
        k = text.find(self._key) if self._key and self.isEnabled() else -1
        if k < 0:
            p.setPen(color)
            p.drawText(self.rect(), flags, text)
        else:                              # three runs: before, the key part in ink2, after
            fm = QFontMetricsF(self.font())
            r = QRectF(self.rect())
            x = 0.0
            for run, pen in ((text[:k], color), (text[k:k + len(self._key)], t.ink2),
                             (text[k + len(self._key):], color)):
                if run:
                    p.setPen(pen)
                    p.drawText(r.adjusted(x, 0.0, 0.0, 0.0), flags, run)
                    x += fm.horizontalAdvance(run)
        p.end()


class ClickableArea(QWidget):
    """A plain area that emits clicked() (mouse, or Space / Enter with the keyboard). Its click is its own (0.3.6:
    accepted, so a LayerCard's header, which opens the row on a click anywhere, does not take it a second time)."""

    clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            e.accept()
            self.clicked.emit()
            return
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


class _ChipSwatch(QWidget):
    """A 22 x 16 white chip (as on paper, in any theme; 0.3.6: radius 2, no border, the mockup's .ricon); subclasses
    paint on it."""

    W, H = 22, 16

    def __init__(self, color: str = "#111111", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(self.W, self.H)

    def color(self) -> str:
        return self._color.name()

    def set_color(self, color: str) -> None:
        c = QColor(color)
        if c.isValid() and c.name() != self._color.name():
            self._color = c
            self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(0.0, 0.0, self.width(), self.height()), 2.0, 2.0)
        self._paint(p)
        p.end()

    def _paint(self, p: QPainter) -> None:
        pass


class ExploSwatch(_ChipSwatch):
    """An exploration row's swatch: a vertical line with a short bar on top (the depth line and its top cap) in the
    row's colour: #111111 (Black), LOOK_GRAY or, for Color, its one colour; a Color row of several colours (0.3.4):
    two or three vertical bars, one per colour (the mockup's swatchFor)."""

    MAX_COLORS = 3
    BLACK = "#111111"                      # an empty list draws this (as a Color row with no symbol is drawn)

    def __init__(self, color: str = "#111111", parent: Optional[QWidget] = None):
        super().__init__(color, parent)
        self._colors: List[QColor] = [QColor(self._color)]

    def colors(self) -> List[str]:
        return [c.name() for c in self._colors]

    def set_colors(self, colors: Sequence[str]) -> None:
        """One colour: the line and its cap; two or three: bars (more are left out); none: black."""
        cs = [QColor(c) for c in list(colors or [])[:self.MAX_COLORS]]
        cs = [c for c in cs if c.isValid()] or [QColor(self.BLACK)]
        if [c.name() for c in cs] != self.colors():
            self._colors = cs
            self._color = QColor(cs[0])
            self.update()

    def set_color(self, color: str) -> None:
        self.set_colors([color])

    def _paint(self, p: QPainter) -> None:
        sx, sy = self.width() / 22.0, self.height() / 16.0
        if len(self._colors) > 1:
            for i, c in enumerate(self._colors):
                pen = QPen(c, 2.2)
                pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                p.setPen(pen)
                x = (6.0 + 5.0 * i) * sx
                p.drawLine(QPointF(x, 3.0 * sy), QPointF(x, 14.0 * sy))
            return
        pen = QPen(self._colors[0], 1.6)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        p.drawLine(QPointF(11.0 * sx, 3.0 * sy), QPointF(11.0 * sx, 14.0 * sy))
        pen.setWidthF(1.2)
        p.setPen(pen)
        p.drawLine(QPointF(8.0 * sx, 3.0 * sy), QPointF(14.0 * sx, 3.0 * sy))


class StyleChips(QWidget):
    """The colours a Color row reads from its layer's style (0.3.4, the mockup's style box): wrapping chips, each an
    11 px circle of the colour with a thin dark border and its label, then a muted "+ N more". A label is cut with "…"
    only when it is wider than the whole row; the tooltip lists every label. Painted (no child widgets), with a height
    for its width."""

    DOT = 11                               # px, the circle
    DOT_GAP = 4                            # px, circle to label
    CHIP_GAP = 10                          # px between chips
    LINE_GAP = 3                           # px between lines
    BORDER = "#232323"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._items: List[Tuple[str, str]] = []
        self._more = 0
        sp = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    # ---- data
    def set_items(self, items: Sequence[Tuple[str, str]], more: int = 0) -> None:
        """`items`: (label, "#rrggbb") in the order shown; `more`: how many are not shown ("+ N more")."""
        items = [(str(lab), QColor(c).name()) for lab, c in items]
        more = max(0, int(more))
        if items == self._items and more == self._more:
            return
        self._items, self._more = items, more
        self.setToolTip("\n".join(lab for lab, _c in items))
        self.updateGeometry()
        self.update()

    def items(self) -> List[Tuple[str, str]]:
        return list(self._items)

    def more(self) -> int:
        return self._more

    def more_text(self) -> str:
        return f"+ {self._more} more" if self._more else ""

    # ---- geometry
    def _font(self) -> QFont:
        return _scaled_font(self.font(), 0.9)

    def _line_h(self, fm: QFontMetrics) -> int:
        return max(self.DOT, fm.height())

    def _layout(self, width: int):
        """[(x, line, label as drawn, colour or "" for the more text)] for `width`, and the number of lines."""
        fm = QFontMetrics(self._font())
        width = max(1, int(width))
        out, x, line = [], 0, 0
        pieces = [(lab, c) for lab, c in self._items] + ([(self.more_text(), "")] if self._more else [])
        for lab, c in pieces:
            mark = self.DOT + self.DOT_GAP if c else 0
            w = mark + fm.horizontalAdvance(lab)
            if x > 0 and x + w > width:
                x, line = 0, line + 1
            text = lab
            if w > width:                              # wider than the whole row: cut
                text = fm.elidedText(lab, Qt.TextElideMode.ElideRight, max(0, width - mark))
                w = mark + fm.horizontalAdvance(text)
            out.append((x, line, text, c))
            x += w + self.CHIP_GAP
        return out, (line + 1 if out else 0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        _out, lines = self._layout(width)
        if not lines:
            return 0
        lh = self._line_h(QFontMetrics(self._font()))
        return lines * lh + (lines - 1) * self.LINE_GAP

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self._font())
        out, _lines = self._layout(10 ** 6)
        w = max((x + (self.DOT + self.DOT_GAP if c else 0) + fm.horizontalAdvance(t) for x, _l, t, c in out),
                default=0)
        return QSize(w, self.heightForWidth(self.width() if self.width() > 1 else w))

    def minimumSizeHint(self) -> QSize:
        return QSize(self.DOT + self.DOT_GAP + 12, self._line_h(QFontMetrics(self._font())) if self._items else 0)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.updateGeometry()

    def paintEvent(self, _e) -> None:
        t = theme_for(self.palette())
        f = self._font()
        fm = QFontMetrics(f)
        lh = self._line_h(fm)
        out, _lines = self._layout(self.width())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setFont(f)
        ink = t.field_ink if self.isEnabled() else t.disabled
        for x, line, text, c in out:
            top = line * (lh + self.LINE_GAP)
            if c:
                p.setPen(QPen(QColor(self.BORDER), 1.0))
                p.setBrush(QColor(c))
                d = self.DOT - 1.0
                p.drawEllipse(QRectF(x + 0.5, top + (lh - self.DOT) / 2.0 + 0.5, d, d))
                tx = x + self.DOT + self.DOT_GAP
                p.setPen(ink)
            else:
                tx = x
                p.setPen(t.muted)
            p.drawText(QRectF(tx, top, max(1, self.width() - tx), lh),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        p.end()

    def painted(self) -> List[Tuple[str, str]]:
        """(label as drawn, colour; "" for the more text) at the current width (tests)."""
        return [(text, c) for _x, _l, text, c in self._layout(self.width())[0]]


class SymbolSwatch(_ChipSwatch):
    """An Other features row's swatch (0.3.6): its symbol (ui.symbol_icons: the sheets' own geometry, in the row's
    colour) or, for a polygon row, its bracket mark in the row's colour and line style, on the white chip."""

    def __init__(self, shape: str = "asterisk", color: str = "#1f6fb2", parent: Optional[QWidget] = None):
        super().__init__(color, parent)
        self._shape = shape
        self._kind = "symbol"
        self._style = "solid"
        self._pm: Optional[QPixmap] = None
        self._pm_key: Optional[tuple] = None

    def shape(self) -> str:
        """The symbol key ("" while it shows a bracket)."""
        return self._shape if self._kind == "symbol" else ""

    def kind(self) -> str:
        """"symbol" | "bracket"."""
        return self._kind

    def bracket_style(self) -> str:
        return self._style

    def set_symbol(self, shape: str, color: str) -> None:
        if (self._kind, self._shape) != ("symbol", shape):
            self._kind, self._shape = "symbol", shape
            self.update()
        self.set_color(color)

    def set_bracket(self, color: str, style: str = "solid") -> None:
        if (self._kind, self._style) != ("bracket", style):
            self._kind, self._style = "bracket", style
            self.update()
        self.set_color(color)

    def _paint(self, p: QPainter) -> None:
        dpr = self.devicePixelRatioF()
        key = (self._kind, self._shape if self._kind == "symbol" else self._style, self.color(), dpr)
        if key != self._pm_key:
            if self._kind == "bracket":
                self._pm = bracket_pixmap(self.color(), self._style, self.W, self.H, dpr)
            else:
                self._pm = symbol_pixmap(self._shape, self.color(), self.W, self.H, dpr)
            self._pm_key = key
        p.drawPixmap(0, 0, self._pm)


class BarSwatch(QWidget):
    """The Ground row's icon (0.3.6): a 16 x 4 bar in its colour, centred in 22 x 16."""

    W, H = 22, 16

    def __init__(self, color: str = "#111111", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(self.W, self.H)

    def color(self) -> str:
        return self._color.name()

    def set_color(self, color: str) -> None:
        c = QColor(color)
        if c.isValid() and c.name() != self._color.name():
            self._color = c
            self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._color)
        p.drawRoundedRect(QRectF((self.width() - 16.0) / 2.0, (self.height() - 4.0) / 2.0, 16.0, 4.0), 1.0, 1.0)
        p.end()


class StatusDot(QWidget):
    """The status line's 7 px dot (0.3.6): "ok" green, "warn" amber, "error" red, "" hidden."""

    COLORS = {"ok": "ok", "warn": "warn", "error": "error"}

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._state = ""
        self.setFixedSize(7, 7)
        self.hide()

    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        state = state if state in self.COLORS else ""
        if state != self._state:
            self._state = state
            self.update()
        self.setVisible(bool(state))

    def paintEvent(self, _e) -> None:
        if not self._state:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(getattr(theme_for(self.palette()), self.COLORS[self._state]))
        p.drawEllipse(QRectF(0.0, 0.0, self.width(), self.height()))
        p.end()


# ---------------------------------------------------------------- "More" pills (0.3.6, D6)
class _DisclosureButton(QAbstractButton):
    """A round pill as wide as its text (it shrinks, the text elided, only when the panel is narrower): a caret 4 px
    before the text. Closed: field fill, field_line border, link text; open: row_open fill, row_rail border, ink."""

    H = 22
    PAD_L, CARET, GAP, PAD_R = 8.0, 5.0, 4.0, 10.0

    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFont(_px_font(self.font(), 11.0, QFont.Weight.DemiBold))
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.H)

    def _text_x(self) -> float:
        return self.PAD_L + self.CARET + self.GAP

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        return QSize(int(self._text_x() + fm.horizontalAdvance(self.text()) + self.PAD_R + 0.5), self.H)

    def minimumSizeHint(self) -> QSize:
        return QSize(min(48, self.sizeHint().width()), self.H)

    def paintEvent(self, _e) -> None:
        t = theme_for(self.palette())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        h, w = float(self.height()), float(self.width())
        on = self.isChecked()
        border, fill = (t.row_rail, t.row_open) if on else (t.field_line, t.field)
        ink = t.disabled if not self.isEnabled() else (t.ink if on else t.link)
        rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        p.setPen(QPen(border, 1.0))
        p.setBrush(fill)
        p.drawRoundedRect(rect, rect.height() / 2.0, rect.height() / 2.0)
        cy, x = h / 2.0, self.PAD_L
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        if on:
            tri = [QPointF(x - 0.5, cy - 2.0), QPointF(x + 5.5, cy - 2.0), QPointF(x + 2.5, cy + 2.0)]
        else:
            tri = [QPointF(x, cy - 3.0), QPointF(x + 5.0, cy), QPointF(x, cy + 3.0)]
        p.drawPolygon(QPolygonF(tri))
        p.setPen(ink)
        p.setFont(self.font())
        fm = QFontMetrics(self.font())
        tx = self._text_x()
        text = fm.elidedText(self.text(), Qt.TextElideMode.ElideRight, int(max(0.0, w - tx - self.PAD_R + 2.0)))
        p.drawText(QRectF(tx, 0.0, w - tx, h), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        if self.hasFocus():
            p.setPen(QPen(ink, 1, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            inner = rect.adjusted(2.0, 2.0, -2.0, -2.0)
            p.drawRoundedRect(inner, inner.height() / 2.0, inner.height() / 2.0)
        p.end()


class _MoreBody(QFrame):
    """A Disclosure's dashed box (row_rail)."""

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        paint_dashed_box(self, theme_for(self.palette()).row_rail)


class Disclosure(QWidget):
    """Settings set once, folded under a round pill inside a section ("Units & datum"; folded when created); open,
    they show in a dashed box 5 px under the pill (0.3.6, D6)."""

    toggled = pyqtSignal(bool)

    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.button = _DisclosureButton(text, self)
        self.body = _MoreBody(self)
        self.body.setObjectName("xsMoreBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(10, 9, 10, 9)
        self.body_layout.setSpacing(7)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)                  # (a hidden body takes no spacing)
        lay.addWidget(self.button, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.body)
        self.body.hide()
        self.button.toggled.connect(self._on_toggled)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def addWidget(self, w: QWidget) -> QWidget:
        self.body_layout.addWidget(w)
        return w

    def text(self) -> str:
        return self.button.text()

    def setText(self, text: str) -> None:
        if text != self.button.text():
            self.button.setText(text)
            self.button.updateGeometry()
            self.button.update()

    def isExpanded(self) -> bool:
        return self.button.isChecked()

    def setExpanded(self, on: bool) -> None:
        self.button.setChecked(bool(on))

    def _on_toggled(self, on: bool) -> None:
        self.body.setVisible(on)
        self.toggled.emit(on)


# ---------------------------------------------------------------- Verbose and hints (0.3.6, D12, D13)
VERBOSE_KEY = "verbose"                # per user (QgsSettings "xsections/verbose" via settings_store): "1" on


class VerboseHub(QObject):
    """The one Verbose switch of the session: off by default, stored per user (never in the project). Every Hint
    follows its `changed`."""

    changed = pyqtSignal(bool)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._on = self._stored()

    @staticmethod
    def _stored() -> bool:
        return settings_store.user_value(VERBOSE_KEY, "0") == "1"

    def value(self) -> bool:
        return self._on

    def reload(self) -> None:
        """Read the stored value again (emits changed when it differs; for tests)."""
        on = self._stored()
        if on != self._on:
            self._on = on
            self.changed.emit(on)

    def set_value(self, on: bool) -> None:
        on = bool(on)
        settings_store.set_user_value(VERBOSE_KEY, "1" if on else "0")
        if on != self._on:
            self._on = on
            self.changed.emit(on)


_VERBOSE_HUB: Optional[VerboseHub] = None


def verbose_hub() -> VerboseHub:
    """The one hub (made on first use; it reads the stored value once)."""
    global _VERBOSE_HUB
    if _VERBOSE_HUB is None:
        _VERBOSE_HUB = VerboseHub()
    return _VERBOSE_HUB


def verbose() -> bool:
    """Hints and notes under the controls (the ⋯ menu's Verbose)."""
    return verbose_hub().value()


def set_verbose(on: bool) -> None:
    """Store Verbose ("1" / "0") for this user; every Hint follows (changed is emitted only when it changed)."""
    verbose_hub().set_value(on)


class Hint(QLabel):
    """An explanatory line under a control (0.3.6, D13): shown exactly when its owner wants it (wanted(): it has
    something to say) and Verbose is on. Code never shows or hides a Hint itself, only setWanted; isHidden() then
    reflects both. Word wrapped, 11 px, muted; `warn` amber (a guess); a `<b>` run in ink2 (the mockup's .hint b);
    setHead: a short one beside a subsection heading ("top drawn first"), in the link colour."""

    PX = 11.0

    def __init__(self, text: str = "", warn: bool = False, rich: bool = True, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsHint")
        self._raw = ""
        self._rich = bool(rich)
        self._wanted = True
        self.setTextFormat(Qt.TextFormat.RichText if rich else Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setFont(_px_font(self.font(), self.PX))
        self.setProperty("warn", "true" if warn else "false")
        self.setProperty("head", "false")
        self.setText(text)
        verbose_hub().changed.connect(self._sync)
        self._sync()

    # ---- text (`<b>` in ink2)
    def setText(self, text: str) -> None:
        self._raw = str(text)
        super().setText(self._shown())

    def text(self) -> str:
        return self._raw

    def _shown(self) -> str:
        if not self._rich or "<b>" not in self._raw:
            return self._raw
        c = theme_for(self.palette()).ink2.name()
        return self._raw.replace("<b>", f'<span style="color:{c}; font-weight:600">').replace("</b>", "</span>")

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        if e.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange) and "<b>" in self._raw:
            super().setText(self._shown())

    # ---- looks
    def setWarn(self, on: bool) -> None:
        self._set_prop("warn", on)

    def isWarn(self) -> bool:
        return self.property("warn") == "true"

    def setHead(self, on: bool) -> None:
        """A head hint: one line beside a subsection heading, in the link colour."""
        self._set_prop("head", on)
        self.setWordWrap(not on)
        self.setSizePolicy(QSizePolicy.Policy.Preferred if on else QSizePolicy.Policy.Ignored,
                           QSizePolicy.Policy.Fixed if on else QSizePolicy.Policy.Preferred)
        if on:
            self.setFont(_px_font(QApplication.font(self), 11.0, MEDIUM))

    def _set_prop(self, name: str, on: bool) -> None:
        value = "true" if on else "false"
        if self.property(name) != value:
            self.setProperty(name, value)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    # ---- shown with Verbose
    def wanted(self) -> bool:
        return self._wanted

    def setWanted(self, on: bool) -> None:
        self._wanted = bool(on)
        self._sync()

    @pyqtSlot(bool)
    def _sync(self, *_args) -> None:
        # (a slot, so Qt drops the hub's connection when the Hint is deleted: the hub lives for the whole session, and
        # a plain method's connection would stay behind for every row ever built)
        show = self._wanted and verbose()
        if self.isWindow():                # not placed yet: never shown as a window of its own; one that is not
            hidden = self.isHidden() and self.testAttribute(Qt.WidgetAttribute.WA_WState_ExplicitShowHide)
            if show and hidden:            # explicitly hidden shows with the widget it is put into
                self.setAttribute(Qt.WidgetAttribute.WA_WState_ExplicitShowHide, False)
            elif not show and not hidden:
                QLabel.setVisible(self, False)
        elif self.isHidden() == show:
            QLabel.setVisible(self, show)

    def event(self, e) -> bool:
        out = super().event(e)
        if e.type() == QEvent.Type.ParentChange:
            self._sync()
        return out


class Readout(Hint):
    """A section's readout (0.3.6: a Verbose note, 2.6): the muted rich text at the bottom of a section, selectable,
    at 0.9 x the font, under a dashed rule (the stylesheet's xsReadout)."""

    PX = 10.8

    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(text, rich=True, parent=parent)
        self.setObjectName("xsReadout")
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)


# ---------------------------------------------------------------- checks: problems and guesses (0.3.6, D14, D15)
@dataclass
class CardInfo:
    """One block of a check card: a round amber icon, a bold title, a source line ("layer · where it came from"), a
    term -> value list, an optional note, and the buttons it wants."""
    title: str
    source: str = ""
    items: Sequence[Tuple[str, str, str]] = ()      # (term, value, suffix): the value in monospace when `mono`,
    mono: bool = True                               # the suffix muted in the app font (" · elevations")
    note: str = ""
    more: int = 0                                   # items left out of `items` ("… and N more")
    actions: Sequence[Tuple[str, str]] = ()         # (key, button text), e.g. ("open_water", "Open Water")


@dataclass
class Problem:
    """A real problem of a row (D14): its one amber line, its card block, what it counts on the badge."""
    line: str
    card: CardInfo
    count: int = 1


# the card's action keys: open_layer, open_depths, open_water (an exploration row: its editor on that tab),
# looks_right (a guess), open (the row's editor)
PRIMARY_ACTION = "looks_right"


def card_actions(blocks: Sequence[CardInfo]) -> List[Tuple[str, str]]:
    """The buttons of a card: its blocks' actions in order, each key once."""
    seen, out = set(), []
    for b in blocks:
        for key, text in b.actions or ():
            if key not in seen:
                seen.add(key)
                out.append((key, text))
    return out


def _card_items(b: CardInfo) -> Tuple[List[Tuple[str, str, str]], int]:
    """A block's (term, value, suffix) lines as shown (at most CARD_ITEMS) and how many more there are."""
    rows = [tuple((tuple(it) + ("", "", ""))[:3]) for it in (b.items or ())]
    shown = rows[:CARD_ITEMS]
    return [(str(a), str(v), str(s)) for a, v, s in shown], max(0, int(b.more)) + len(rows) - len(shown)


class CheckBadge(QAbstractButton):
    """A row's amber badge (0.3.6): "check" for a guess, the number of problem items otherwise. A click (Space,
    Enter) opens its check card or, open, closes it (find_card_host(self).toggle); hover never opens it. `blocks` and
    `actions` (the card's content) are set by its LayerCard; a card button emits actionTriggered(key)."""

    actionTriggered = pyqtSignal(str)
    PAD_L, MARK, GAP, PAD_R = 6.0, 8.0, 4.0, 7.0

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsBadge")
        self.blocks: List[CardInfo] = []
        self.actions: List[Tuple[str, str]] = []
        self._open = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setToolTip("Show what to check")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFont(_px_font(self.font(), 10.5, QFont.Weight.DemiBold))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(BADGE_H)
        self.clicked.connect(self._on_clicked)

    def set_check_text(self, text: str) -> None:
        if text != self.text():
            self.setText(text)
            self.setAccessibleName(f"{text}: show what to check")
            self.updateGeometry()
            self.update()

    def isOpen(self) -> bool:
        """Its card is open."""
        return self._open

    def _set_open(self, on: bool) -> None:
        if bool(on) != self._open:
            self._open = bool(on)
            self.update()

    def _on_clicked(self, *_args) -> None:
        find_card_host(self).toggle(self)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            return
        super().keyPressEvent(e)

    def sizeHint(self) -> QSize:
        fm = QFontMetricsF(self.font())
        w = self.PAD_L + self.MARK + self.GAP + fm.horizontalAdvance(self.text()) + self.PAD_R
        return QSize(int(w + 0.99), BADGE_H)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _e) -> None:
        t = theme_for(self.palette())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        if self._open:
            fill, border, ink = t.amber, t.amber, t.pop
        else:
            fill, border, ink = t.amber_bg, t.pop_line, t.amber
        rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        p.setPen(QPen(border, 1.0))
        p.setBrush(fill)
        p.drawRoundedRect(rect, rect.height() / 2.0, rect.height() / 2.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        p.drawPolygon(_triangle(self.PAD_L, h / 2.0 - 3.5, self.MARK, 7.0))
        p.setPen(ink)
        p.setFont(self.font())
        tx = self.PAD_L + self.MARK + self.GAP
        p.drawText(QRectF(tx, 0.0, w - tx, h), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                   self.text())
        if self.hasFocus():
            p.setPen(QPen(ink, 1, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            inner = rect.adjusted(2.0, 2.0, -2.0, -2.0)
            p.drawRoundedRect(inner, inner.height() / 2.0, inner.height() / 2.0)
        p.end()


class _CardIcon(QWidget):
    """A card block's 18 px round amber_bg icon with its amber 9 x 8 triangle."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(18, 18)

    def paintEvent(self, _e) -> None:
        t = theme_for(self.palette())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(t.amber_bg)
        p.drawEllipse(QRectF(0.0, 0.0, 18.0, 18.0))
        p.setBrush(t.amber)
        p.drawPolygon(_triangle(4.5, 4.5, 9.0, 8.0))
        p.end()


class CheckCard(QFrame):
    """The check card (0.3.6, D15): a child widget of the panel (not a window), CARD_W wide (narrower panels: the
    panel's width - 8), painted by hand: rounded, a 1 px border, a 3 px amber top edge, a soft shadow. Each block: the
    round icon, the bold title and the source line; under a rule its term -> value lines (values in monospace, elided,
    never wrapped; "… and N more"); its note. A footer of buttons (the primary one navy) when any block has actions;
    a button emits actionTriggered(key)."""

    actionTriggered = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsCheckCard")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._titles: List[str] = []
        self._items: List[Tuple[str, str, str]] = []
        self._notes: List[str] = []
        self._buttons: List[QPushButton] = []
        self._foot: Optional[QWidget] = None
        self._content: Optional[QWidget] = None
        self._in_theme = False                        # setting its stylesheet (_apply_theme)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(1, 3, 1, 1)      # the border, the amber top edge
        self._lay.setSpacing(0)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(24)
        self._shadow.setOffset(0, 6)
        self.setGraphicsEffect(self._shadow)
        self._apply_theme()

    # ---- read-backs (tests)
    def titles(self) -> List[str]:
        return list(self._titles)

    def items(self) -> List[Tuple[str, str, str]]:
        """Every (term, value, suffix) shown, block after block."""
        return list(self._items)

    def notes(self) -> List[str]:
        return list(self._notes)

    def buttons(self) -> List[QPushButton]:
        return list(self._buttons)

    # ---- content
    def set_content(self, blocks: Sequence[CardInfo], actions: Sequence[Tuple[str, str]] = ()) -> None:
        if self._content is not None:
            self._lay.removeWidget(self._content)
            self._content.hide()
            self._content.deleteLater()
        self._titles, self._items, self._notes, self._buttons, self._foot = [], [], [], [], None
        content = QWidget(self)
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        base = self.font()
        for i, b in enumerate(blocks):
            if i:
                cl.addWidget(_Rule(1, content))
            cl.addWidget(self._block_head(b, base, content))
            rows, more = _card_items(b)
            if rows or more:
                cl.addWidget(_Rule(1, content))
                cl.addWidget(self._block_items(b, rows, more, base, content))
            if b.note:
                # (its padding in a layout, as the blocks above: the stylesheet's re-polish (_apply_theme) resets a
                # label's own contents margins)
                box = QWidget(content)
                nl = QVBoxLayout(box)
                nl.setContentsMargins(11, 0, 11, 8)
                nl.setSpacing(0)
                nl.addWidget(self._label(b.note, "xsCardNote", _px_font(base, 11.0), box, wrap=True))
                cl.addWidget(box)
                self._notes.append(b.note)
            self._titles.append(b.title)
        if actions:
            cl.addWidget(_Rule(1, content))
            foot = QWidget(content)
            fl = QHBoxLayout(foot)
            fl.setContentsMargins(9, 7, 9, 7)
            fl.setSpacing(6)
            fl.addStretch(1)
            keys = [k for k, _t in actions]
            primary = PRIMARY_ACTION if PRIMARY_ACTION in keys else keys[-1]
            for key, text in actions:
                btn = QPushButton(text, foot)
                btn.setObjectName("xsCardPrimary" if key == primary else "xsCardButton")
                btn.setFont(_px_font(base, 11.0, MEDIUM))
                btn.setFixedHeight(22)
                btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setProperty("action", key)
                btn.clicked.connect(lambda _c=False, k=key: self.actionTriggered.emit(k))
                fl.addWidget(btn, 0)
                self._buttons.append(btn)
            cl.addWidget(foot)
            self._foot = foot
        self._content = content
        self._lay.addWidget(content)
        content.show()                     # now, so a card already open measures its new content
        self._apply_theme()
        self.update()

    def _label(self, text: str, name: str, font: QFont, parent: QWidget, wrap: bool = False) -> QLabel:
        lab = QLabel(text, parent)
        lab.setObjectName(name)
        lab.setFont(font)
        lab.setTextFormat(Qt.TextFormat.PlainText)
        lab.setWordWrap(wrap)
        # (heightForWidth kept, as setWordWrap set it: a new policy drops it, and since the 0.3.7 fix no re-polish
        # (_apply_theme) brings it back; without it the card is sized by sizeHint, and a long title is cut off)
        pol = QSizePolicy(QSizePolicy.Policy.Ignored if wrap else QSizePolicy.Policy.Preferred,
                          QSizePolicy.Policy.Preferred if wrap else QSizePolicy.Policy.Fixed)
        pol.setHeightForWidth(wrap)
        lab.setSizePolicy(pol)
        return lab

    def _block_head(self, b: CardInfo, base: QFont, parent: QWidget) -> QWidget:
        w = QWidget(parent)
        g = QGridLayout(w)
        g.setContentsMargins(11, 9, 11, 8)
        g.setHorizontalSpacing(7)
        g.setVerticalSpacing(2)
        g.addWidget(_CardIcon(w), 0, 0, 2, 1, Qt.AlignmentFlag.AlignTop)
        g.addWidget(self._label(b.title, "xsCardTitle", _px_font(base, 12.5, QFont.Weight.DemiBold), w, wrap=True),
                    0, 1)
        if b.source:
            g.addWidget(self._label(b.source, "xsCardSource", _px_font(base, 11.0), w, wrap=True), 1, 1)
        g.setColumnStretch(1, 1)
        return w

    def _block_items(self, b: CardInfo, rows: Sequence[Tuple[str, str, str]], more: int, base: QFont,
                     parent: QWidget) -> QWidget:
        w = QWidget(parent)
        g = QGridLayout(w)
        g.setContentsMargins(11, 6, 11, 8)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(3)
        small = _px_font(base, 11.0)
        mono = QFont(small)
        mono.setFamilies(["Consolas", "Courier New", "monospace"])
        mono.setStyleHint(QFont.StyleHint.Monospace)
        for r, (term, value, suffix) in enumerate(rows):
            g.addWidget(self._label(term, "xsCardTerm", small, w), r, 0)
            cell = QWidget(w)
            hl = QHBoxLayout(cell)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(0)
            val = ElidedLabel(value, parent=cell)
            val.setObjectName("xsCardValue")
            val.setFont(mono if b.mono else small)
            val.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            val.setToolTip(value)
            hl.addWidget(val, 0)
            if suffix:
                hl.addWidget(self._label(suffix, "xsCardSuffix", small, cell), 0)
            hl.addStretch(1)
            g.addWidget(cell, r, 1)
            self._items.append((term, value, suffix))
        if more:
            g.addWidget(self._label(f"… and {more} more", "xsCardMore", small, w), len(rows), 0, 1, 2)
        g.setColumnStretch(1, 1)
        return w

    # ---- look
    def _apply_theme(self) -> None:
        """The card's colours from its palette. Its stylesheet is set only when it changes (0.3.7 fix, with
        changeEvent: under an application stylesheet, QGIS's Night Mapping and Blend of Gray themes, setStyleSheet
        re-polishes the card and the polish sets its palette, a PaletteChange; 0.3.6 answered it here again and
        recursed until the stack overflowed, building the panel)."""
        t = theme_for(self.palette())
        self._shadow.setColor(QColor(0, 0, 0, 102) if t.dark else QColor(16, 32, 40, 51))
        muted = css(t.muted)
        sheet = f"""
QLabel#xsCardTitle {{ color: {css(t.ink)}; }}
QLabel#xsCardSource, QLabel#xsCardTerm, QLabel#xsCardSuffix, QLabel#xsCardNote, QLabel#xsCardMore {{ color: {muted}; }}
""" + _card_button_rules(t)
        if sheet == self.styleSheet():
            return
        self._in_theme = True
        try:
            self.setStyleSheet(sheet)
        finally:
            self._in_theme = False

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        # (not the palette changes its own stylesheet brings, while _apply_theme sets it)
        if e.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange) and not self._in_theme:
            self._apply_theme()

    def paintEvent(self, _e) -> None:
        t = theme_for(self.palette())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        outer = _corner_path(r, 6, 6, 6, 6)
        p.fillPath(outer, t.pop_line)
        p.save()
        p.setClipPath(outer)
        p.fillRect(QRectF(0.0, 0.0, r.width(), 3.0), t.amber)
        p.restore()
        inner = _corner_path(r.adjusted(1.0, 3.0, -1.0, -1.0), (5, 3), (5, 3), 5, 5)
        p.fillPath(inner, t.pop)
        if self._foot is not None and self._content is not None and not self._foot.isHidden():
            g = self._foot.geometry().translated(self._content.pos())
            p.save()
            p.setClipPath(inner)
            p.fillRect(QRectF(g).adjusted(-1.0, 0.0, 1.0, 1.0), t.card_foot)
            p.restore()
        p.end()


class CardHost(QObject):
    """The one check card of a panel (0.3.6, D15; the mockup's app.js): a click on a badge opens its card under the
    badge, at its right (above it when it would not fit below); a second click on that badge closes it, a click on
    another badge moves it there. It never opens on hover; it closes CARD_CLOSE_MS after the pointer has left both
    the badge and the card, after an action button (once the badge has emitted actionTriggered), when the badge is
    hidden or deleted, when the panel is hidden, and on close() (the dock: scrolling, a section closing ...)."""

    def __init__(self, panel: QWidget):
        super().__init__(panel)
        self.panel = panel
        self.card = CheckCard(panel)
        self.card.hide()
        self._badge: Optional[CheckBadge] = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(CARD_CLOSE_MS)
        self._timer.timeout.connect(self.close)
        self.card.installEventFilter(self)
        panel.installEventFilter(self)
        self.card.actionTriggered.connect(self._on_action)

    def badge(self) -> Optional[CheckBadge]:
        return self._badge

    def is_open(self) -> bool:
        return self._badge is not None and not self.card.isHidden()

    def toggle(self, badge: CheckBadge) -> None:
        if self.is_open() and self._badge is badge:
            self.close()
        else:
            self.open(badge)

    def open(self, badge: CheckBadge) -> None:
        if self._badge is not None and self._badge is not badge:
            self._release()
        self._timer.stop()
        if self._badge is not badge:
            self._badge = badge
            badge.installEventFilter(self)
            badge.destroyed.connect(self._on_badge_destroyed)
        panel, card = self.panel, self.card
        card.set_content(badge.blocks, badge.actions)
        w = min(CARD_W, max(1, panel.width() - 8))
        card.setFixedWidth(w)
        card.layout().activate()
        h = card.heightForWidth(w) if card.hasHeightForWidth() else card.sizeHint().height()
        h = max(h, card.minimumSizeHint().height(), 1)
        card.setFixedHeight(h)
        br = self._to_panel(badge, QPoint(badge.width(), badge.height()))
        left = max(4, min(br.x() - w, panel.width() - w - 4))
        top = br.y() + 1
        if top + h > panel.height() - 4:
            top = self._to_panel(badge, QPoint(0, 0)).y() - h - 1
        card.move(left, top)
        card.show()
        card.raise_()
        badge._set_open(True)

    def _to_panel(self, w: QWidget, pt: QPoint) -> QPoint:
        if self.panel.isAncestorOf(w):
            return w.mapTo(self.panel, pt)
        return self.panel.mapFromGlobal(w.mapToGlobal(pt))

    def close(self) -> None:
        self._timer.stop()
        self._release()
        self.card.hide()

    def _release(self) -> None:
        b, self._badge = self._badge, None
        if b is None:
            return
        try:
            b._set_open(False)
            b.removeEventFilter(self)
            b.destroyed.disconnect(self._on_badge_destroyed)
        except (RuntimeError, TypeError):
            pass

    def _on_badge_destroyed(self, *_args) -> None:
        self._badge = None
        self._timer.stop()
        try:
            self.card.hide()
        except RuntimeError:
            pass

    def _on_action(self, key: str) -> None:
        b = self._badge
        if b is not None:
            try:
                b.actionTriggered.emit(key)
            except RuntimeError:
                pass
        self.close()

    def eventFilter(self, obj, ev) -> bool:
        et = ev.type()
        if obj is self.panel:
            if et == QEvent.Type.Hide and self.is_open():
                self.close()
            return False
        if obj is self.card or (self._badge is not None and obj is self._badge):
            if et == QEvent.Type.Enter:
                self._timer.stop()
            elif et == QEvent.Type.Leave:
                if self.is_open():
                    self._timer.start(CARD_CLOSE_MS)
            elif et == QEvent.Type.Hide and obj is self._badge:
                self.close()
        return False


def find_card_host(w: QWidget) -> CardHost:
    """The CardHost of `w`'s panel: the first ancestor (or `w` itself) with an attribute `_xs_card_host`; without one
    (a row tested on its own) a host is made on `w.window()` and kept there."""
    x = w
    while x is not None:
        host = getattr(x, "_xs_card_host", None)
        if host is not None:
            return host
        x = x.parentWidget()
    top = w.window()
    host = CardHost(top)
    top._xs_card_host = host
    return host


# ---------------------------------------------------------------- option buttons and their popups (0.3.7, D1, D2)
def _tab_focusable(w: QWidget) -> bool:
    """`w` takes the focus with Tab (its policy has TabFocus) and is enabled and shown."""
    return bool(w.focusPolicy().value & Qt.FocusPolicy.TabFocus.value) and w.isEnabled() and w.isVisible()


def _within(w: Optional[QWidget], ancestor: QWidget) -> bool:
    """`w` is `ancestor` or below it, following parentWidget() ACROSS windows (a combo box's drop-down list and a line
    edit's context menu are windows whose parent chain leads back into the panel; QWidget.isAncestorOf stops at
    windows)."""
    x = w
    while x is not None:
        if x is ancestor:
            return True
        x = x.parentWidget()
    return False


def _flush_layouts(w: QWidget, sweeps: int = 3) -> None:
    """Send the LayoutRequests posted to `w` and its descendants now, the deepest first (0.3.7 fix). A field that
    restacks for a new width (a pair) asks its parents again one posted event per level, so a popup measured as it
    shows, after a change made while it was hidden (the scroll bar, Verbose, the dock's width), is measured too short;
    each sweep settles what the one before posted."""
    for _ in range(sweeps):
        for x in reversed([w] + w.findChildren(QWidget)):      # (children are listed after their parents)
            QApplication.sendPostedEvents(x, QEvent.Type.LayoutRequest)


class OptionButton(QAbstractButton):
    """One option button of a section (0.3.7, D1): its title over a one-line muted summary of its settings (elided
    "…"), a small chevron at the right; open (its popup showing): the band's fill and outline, a row_rail inner left
    edge, the chevron up. A click toggles its popup (OptionGrid). (No button text: "Water & screens" would make a
    mnemonic shortcut; the title is the accessible name.)"""

    PAD = 9.0                          # the title and summary's left edge (the mockup's padding)
    ROOM = 29.0                        # what they leave free of the width: the padding and the chevron's 20 px

    def __init__(self, title: str, tip: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsOptionButton")
        self._title = str(title)
        self._tip = str(tip or "")
        self._summary = ""
        self._open = False
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)       # (a mouse click does not take the focus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(OPT_H)
        self._sync()

    # ---- state
    def title(self) -> str:
        return self._title

    def setSummary(self, text: str) -> None:
        text = str(text or "")
        if text != self._summary:
            self._summary = text
            self._sync()
            self.update()

    def summary(self) -> str:
        return self._summary

    def shownSummary(self) -> str:
        """The summary as painted: elided to the width."""
        return QFontMetrics(self._summary_font()).elidedText(self._summary, Qt.TextElideMode.ElideRight,
                                                              int(max(0.0, self.width() - self.ROOM)))

    def setTip(self, tip: str) -> None:
        self._tip = str(tip or "")
        self._sync()

    def isOpen(self) -> bool:
        return self._open

    def setOpen(self, on: bool) -> None:
        """Paint state only (OptionGrid calls it)."""
        if bool(on) != self._open:
            self._open = bool(on)
            self.update()

    def _sync(self) -> None:
        self.setAccessibleName(self._title)
        self.setAccessibleDescription(self._summary)
        self.setToolTip("\n".join(x for x in (self._tip, self._summary) if x))   # the full summary, also elided

    # ---- size
    def _title_font(self) -> QFont:
        return _px_font(self.font(), 11.5, QFont.Weight.DemiBold)

    def _summary_font(self) -> QFont:
        return _px_font(self.font(), 10.5)

    def sizeHint(self) -> QSize:
        return QSize(int(self.PAD) + QFontMetrics(self._title_font()).horizontalAdvance(self._title) + 20, OPT_H)

    def minimumSizeHint(self) -> QSize:
        return QSize(60, OPT_H)

    # ---- events
    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):         # (Space: QAbstractButton's own)
            self.click()
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

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        if e.type() == QEvent.Type.FontChange:
            self.updateGeometry()
        if e.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange, QEvent.Type.FontChange):
            self.update()

    def paintEvent(self, _e) -> None:
        t = theme_for(self.palette())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        enabled = self.isEnabled()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = OPT_RADIUS - 0.5
        if self._open:
            fill, line = t.row_open, t.band_line
        else:
            fill, line = t.field, (t.row_rail if self._hover and enabled else t.field_line)
        p.setPen(QPen(line, 1.0))
        p.setBrush(fill)
        p.drawRoundedRect(r, rad, rad)
        if self._open:                     # a 3 px rail-blue inner left edge (the mockup's inset shadow)
            p.save()
            p.setClipPath(_corner_path(QRectF(1.0, 1.0, w - 2.0, h - 2.0), 4, 4, 4, 4))
            p.fillRect(QRectF(1.0, 1.0, 3.0, h - 2.0), t.row_rail)
            p.restore()
        room = max(0.0, w - self.ROOM)
        flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        tf = self._title_font()
        p.setFont(tf)
        p.setPen(t.ink if enabled else t.disabled)
        p.drawText(QRectF(self.PAD, 6.0, room, 14.0), flags,
                   QFontMetrics(tf).elidedText(self._title, Qt.TextElideMode.ElideRight, int(room)))
        if self._summary:
            p.setFont(self._summary_font())
            p.setPen(t.disabled if not enabled else (t.ink2 if self._open else t.muted))
            p.drawText(QRectF(self.PAD, 22.0, room, 13.0), flags, self.shownSummary())
        p.setPen(Qt.PenStyle.NoPen)        # the chevron: down (closed, muted), up (open, row_rail)
        if self._open:
            p.setBrush(t.row_rail)
            tri = [QPointF(w - 17.0, 15.0), QPointF(w - 10.0, 15.0), QPointF(w - 13.5, 11.0)]
        else:
            p.setBrush(t.muted if enabled else t.disabled)
            tri = [QPointF(w - 17.0, 11.0), QPointF(w - 10.0, 11.0), QPointF(w - 13.5, 15.0)]
        p.drawPolygon(QPolygonF(tri))
        if self.hasFocus():
            p.setPen(QPen(t.ink, 1, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(2.0, 2.0, -2.0, -2.0), rad - 2.0, rad - 2.0)
        p.end()


class _PopClose(QAbstractButton):
    """An option popup's ✕ (0.3.7): 20 x 20, an 8 x 8 cross of two 1.3 px round-capped lines (no font glyph) in muted,
    in ink over a rounded hover fill while hovered; Tab reaches it. A click asks the popup to close."""

    SIZE = 20

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._hover = False
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip("Close (Esc)")
        self.setAccessibleName("Close")

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
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
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        hot = self._hover and self.isEnabled()
        if hot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(t.hover)
            p.drawRoundedRect(r, 3.0, 3.0)
        pen = QPen(t.ink if hot else t.muted, 1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        c = r.center()
        p.drawLine(QPointF(c.x() - 4.0, c.y() - 4.0), QPointF(c.x() + 4.0, c.y() + 4.0))
        p.drawLine(QPointF(c.x() - 4.0, c.y() + 4.0), QPointF(c.x() + 4.0, c.y() - 4.0))
        if self.hasFocus():
            p.setPen(QPen(t.ink, 1, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1.5, 1.5, -1.5, -1.5), 3.0, 3.0)
        p.end()


class OptionPopup(QFrame):
    """The popup of an option button (0.3.7, D2): a child of the panel's content (not a window), shown and placed by
    its OptionGrid. Painted by hand: one band-coloured box (row_open, radius POP_RADIUS) with a 1 px band_line outline
    and a notch rising NOTCH_H px over its top edge toward its button; a header (the title, optional widgets after it,
    optional links at the right, a ✕), a 1 px field_line rule, then the body (body_layout). The strip beside the notch
    stays transparent (WA_NoSystemBackground: a grab shows it so too); a press there belongs to the popup and does
    nothing."""

    closeRequested = pyqtSignal()                    # the ✕

    def __init__(self, title: str, after_title: Sequence[QWidget] = (), links: Sequence[QWidget] = (),
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsOptionPopup")          # (no stylesheet rule: it paints itself)
        self._title = str(title)
        self._notch = 30.0                           # as asked (set_notch_x); notch_x() clamps it to the width
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, NOTCH_H + 1, 1, 1)
        lay.setSpacing(0)
        # the header: 8 + 20 + 7 px, 36 with its rule
        self.header = QWidget(self)
        self.header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(10, 8, 8, 7)
        hl.setSpacing(8)
        self.title_label = QLabel(self._title, self.header)
        self.title_label.setObjectName("xsPopTitle")
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setFont(_px_font(self.title_label.font(), 12.0, QFont.Weight.DemiBold))
        hl.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignVCenter)
        for w in after_title:                        # (the Plotted count)
            w.setMaximumHeight(_PopClose.SIZE)
            hl.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        hl.addStretch(1)
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(2)
        for w in links:                              # ("Show all")
            w.setMaximumHeight(_PopClose.SIZE)
            right.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        self.close_button = _PopClose(self.header)
        right.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignVCenter)
        hl.addLayout(right)
        lay.addWidget(self.header)
        lay.addWidget(_Rule(1, self, "field_line"))
        # the body (the mockup's .opb; a caller may set other margins)
        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(10, 9, 10, 11)
        self.body_layout.setSpacing(8)
        lay.addWidget(self.body)
        self.close_button.clicked.connect(self.closeRequested.emit)
        self.hide()

    def title(self) -> str:
        return self._title

    def addWidget(self, w: QWidget) -> QWidget:
        self.body_layout.addWidget(w)
        return w

    def notch_x(self) -> float:
        """The notch's apex, px from the popup's left edge, kept clear of the rounded corners."""
        lo = POP_RADIUS + NOTCH_HALF + 2.0
        hi = self.width() - POP_RADIUS - NOTCH_HALF - 2.0
        return max(lo, min(hi, self._notch))

    def set_notch_x(self, x: float) -> None:
        if float(x) != self._notch:
            self._notch = float(x)
            self.update()

    def box_rect(self) -> QRect:
        """The box under the notch (the shadow plate's place)."""
        return self.rect().adjusted(0, NOTCH_H, 0, 0)

    # (a press on the popup's own ground (its title, a field name, the strip beside the notch) stops here: passed on
    # to the panel's content it would reach OptionGrid's filter as a press outside the popup. Wheel events go on, so
    # the panel still scrolls under the pointer.)
    def mousePressEvent(self, e) -> None:
        e.accept()

    def mouseReleaseEvent(self, e) -> None:
        e.accept()

    def mouseDoubleClickEvent(self, e) -> None:
        e.accept()

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        if e.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self.update()

    def paintEvent(self, _e) -> None:
        t = theme_for(self.palette())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        cx = self.notch_x()
        box = QPainterPath()
        box.addRoundedRect(QRectF(0.5, NOTCH_H + 0.5, w - 1.0, h - NOTCH_H - 1.0), POP_RADIUS - 0.5, POP_RADIUS - 0.5)
        tri = QPainterPath(QPointF(cx - NOTCH_HALF - 1.0, NOTCH_H + 1.5))     # (7 px half-width on the box's top
        tri.lineTo(cx, 0.5)                                                  # edge; its base inside the box, so
        tri.lineTo(cx + NOTCH_HALF + 1.0, NOTCH_H + 1.5)                     # the union has no top border under it)
        tri.closeSubpath()
        shape = box.united(tri).simplified()
        p.fillPath(shape, t.row_open)
        p.setPen(QPen(t.band_line, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(shape)
        p.end()


class _ShadowPlate(QWidget):
    """An option popup's soft shadow (0.3.7): a sibling exactly under its box, stacked just below it, painted in the
    band colour (hidden by the popup above) and carrying the QGraphicsDropShadowEffect (the check card's blur, offset
    and colours, re-read on a palette change). A plate, so that no graphics effect sits over the popup's own fields
    (typing, a scrolling list, crisp text at 2x). A press on it goes to what is under it."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(24)
        self._shadow.setOffset(0, 6)
        self.setGraphicsEffect(self._shadow)
        self._apply_theme()
        self.hide()

    def shadow(self) -> QGraphicsDropShadowEffect:
        return self._shadow

    def _apply_theme(self) -> None:
        self._shadow.setColor(QColor(0, 0, 0, 102) if theme_for(self.palette()).dark else QColor(16, 32, 40, 51))

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        if e.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self._apply_theme()
            self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillPath(_corner_path(QRectF(self.rect()), POP_RADIUS, POP_RADIUS, POP_RADIUS, POP_RADIUS),
                   theme_for(self.palette()).row_open)
        p.end()


class _PressWatcher(QObject):
    """OptionGrid's application event filter, installed only while one of its popups is open: it sees every event of
    the application, so it tests the type first and passes the presses and Esc keys on."""

    TYPES = frozenset((QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.ShortcutOverride,
                       QEvent.Type.KeyPress))

    def __init__(self, grid: "OptionGrid"):
        super().__init__(grid)
        self._grid = grid

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() not in self.TYPES:
            return False
        try:
            return self._grid._app_event(obj, ev)
        except RuntimeError:               # (the panel is going)
            return False


class OptionGrid(QWidget):
    """The option buttons of a section (0.3.7, D1, D2): two columns (one while a title would be cut), OPT_GAP apart,
    and their popups, children of `overlay` (the dock's scroll content), one open at a time. A click on a button opens
    its popup under it, as wide as the grid; it closes on a second click on that button, its ✕, Esc (the focus in the
    overlay or on the scroll area around it), a press anywhere else but the panel's own scroll bar (an application
    event filter, installed only while one is open), the grid being hidden (its section closing), and close_popup().
    It never closes when the pointer leaves or the panel scrolls. While open it follows the grid (the dock resized,
    rows opening above it, the panel scrolled: it is a child of the content) and its own height (a hint shown, the
    list refilled)."""

    popupToggled = pyqtSignal(int, bool)             # (index, open)

    def __init__(self, overlay: QWidget, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsOptionGrid")
        self._overlay = overlay
        self._buttons: List[OptionButton] = []
        self._popups: List[OptionPopup] = []
        self._plates: List[_ShadowPlate] = []
        self._current = -1
        self._cols = 2
        self._watched: List[QWidget] = []
        self._presses = _PressWatcher(self)
        self._filtering = False            # _presses is the application's event filter now
        self._room_set = False             # this grid set the overlay's minimum height
        self._placing = False
        self._again = False
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(OPT_GAP)
        self._grid.setVerticalSpacing(OPT_GAP)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    # ---- options
    def add_option(self, title: str, tip: str, after_title: Sequence[QWidget] = (),
                   links: Sequence[QWidget] = ()) -> Tuple[OptionButton, OptionPopup]:
        """A button and its popup (hidden; its shadow plate with it), in reading order."""
        b = OptionButton(title, tip, self)
        popup = OptionPopup(title, after_title, links, parent=self._overlay)
        plate = _ShadowPlate(self._overlay)
        self._buttons.append(b)
        self._popups.append(popup)
        self._plates.append(plate)
        b.clicked.connect(lambda _checked=False, btn=b: self.toggle(btn))
        popup.closeRequested.connect(self.close_popup)
        self._arrange(self._cols, force=True)
        self._reflow()
        return b, popup

    def buttons(self) -> List[OptionButton]:
        return list(self._buttons)

    def popups(self) -> List[OptionPopup]:
        return list(self._popups)

    def plates(self) -> List[QWidget]:
        """The popups' shadow plates (tests)."""
        return list(self._plates)

    def columns(self) -> int:
        """2, or 1 while the panel is too narrow for a title."""
        return self._cols

    def current(self) -> Optional[OptionPopup]:
        return self._popups[self._current] if self._current >= 0 else None

    def current_index(self) -> int:
        """The open popup's index; -1: none open."""
        return self._current

    def filtering(self) -> bool:
        """The application event filter is installed (only while a popup is open; tests)."""
        return self._filtering

    def _index(self, which: Any) -> int:
        if isinstance(which, int):
            return which if 0 <= which < len(self._buttons) else -1
        for seq in (self._buttons, self._popups):
            for i, x in enumerate(seq):
                if x is which:
                    return i
        return -1

    # ---- layout
    def _arrange(self, n: int, force: bool = False) -> None:
        if n == self._cols and not force:
            return
        self._cols = n
        for b in self._buttons:
            self._grid.removeWidget(b)
        for i, b in enumerate(self._buttons):
            self._grid.addWidget(b, i // n, i % n)
        for c in range(2):
            self._grid.setColumnStretch(c, 1 if c < n else 0)

    def _reflow(self) -> None:
        if not self._buttons or not self.isVisible():  # (a hidden grid has no width yet; its show checks again)
            return
        need = max(b.sizeHint().width() for b in self._buttons)
        self._arrange(2 if (self.width() - OPT_GAP) / 2.0 >= need else 1)

    # ---- open and close
    def toggle(self, which: Any) -> None:
        """`which`: an index, an OptionButton or an OptionPopup. The open one closes, another opens."""
        i = self._index(which)
        if i < 0:
            return
        if i == self._current:
            self.close_popup()
        else:
            self.open_popup(i)

    def open_popup(self, which: Any) -> bool:
        """Open `which`'s popup (closing another open one first); False when the grid is not visible (nothing
        opens)."""
        i = self._index(which)
        if i < 0 or not self.isVisible():
            return False
        if i == self._current:
            return True
        self.close_popup()
        b, popup, plate = self._buttons[i], self._popups[i], self._plates[i]
        keyboard = b.hasFocus()            # (reached with Tab: a mouse click never gives it the focus)
        self._current = i
        b.setOpen(True)
        self._watch()
        self._place()
        plate.show()
        plate.raise_()                     # (on every open: sections built after the popups are later siblings)
        popup.show()
        popup.raise_()
        _flush_layouts(popup)              # (its fields restacked for this width: placed at its final height, so the
        self._place()                      # dock scrolls the whole of it into view; shown: laid out for real)
        QApplication.instance().installEventFilter(self._presses)
        self._filtering = True
        if keyboard:
            target = self._first_focus(popup)
            if target is not None:
                target.setFocus(Qt.FocusReason.TabFocusReason)
        self.popupToggled.emit(i, True)
        return True

    def close_popup(self) -> None:
        """Close the open popup (idempotent): the focus, when it was inside, goes back to its button."""
        i = self._current
        if i < 0:
            self._stop_filtering()
            return
        self._current = -1
        b, popup, plate = self._buttons[i], self._popups[i], self._plates[i]
        focus_in = False
        try:
            focus_in = _within(QApplication.focusWidget(), popup)
            popup.hide()
            plate.hide()
            b.setOpen(False)
        except RuntimeError:               # (the panel is going)
            pass
        self._unwatch()
        self._stop_filtering()
        self._give_room_back()
        if focus_in:
            try:
                if b.isVisible():
                    b.setFocus(Qt.FocusReason.OtherFocusReason)
            except RuntimeError:
                pass
        self.popupToggled.emit(i, False)

    def _stop_filtering(self) -> None:
        if self._filtering:
            self._filtering = False
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self._presses)

    def _first_focus(self, popup: OptionPopup) -> Optional[QWidget]:
        """The first widget of the popup Tab reaches, in focus chain order: in its body first (a field), else in its
        header (Show all, the ✕)."""
        found = None
        x = popup.nextInFocusChain()
        for _ in range(5000):
            if x is None or x is popup:
                break
            if _tab_focusable(x) and popup.isAncestorOf(x):
                if popup.body.isAncestorOf(x):
                    return x
                if found is None:
                    found = x
            x = x.nextInFocusChain()
        return found

    # ---- placing
    def _to_overlay(self, w: QWidget, pt: QPoint) -> QPoint:
        ov = self._overlay
        if ov.isAncestorOf(w):
            return w.mapTo(ov, pt)
        return ov.mapFromGlobal(w.mapToGlobal(pt))

    def _place(self) -> None:
        """Put the open popup under its button, as wide as the grid, its plate under its box; room under it."""
        if self._current < 0:
            return
        if self._placing:                  # (a geometry change while placing: once more when done)
            self._again = True
            return
        self._placing = True
        try:
            for _ in range(4):
                self._again = False
                self._place_once()
                if not self._again or self._current < 0:
                    break
        except RuntimeError:               # (the panel is going)
            pass
        finally:
            self._placing = False

    def _place_once(self) -> None:
        b, popup, plate = self._buttons[self._current], self._popups[self._current], self._plates[self._current]
        x = self._to_overlay(self, QPoint(0, 0)).x()
        w = max(1, self.width())
        y = self._to_overlay(b, QPoint(0, b.height())).y()           # the button's bottom edge: the notch's apex
        popup.setFixedWidth(w)
        popup.layout().activate()
        h = popup.heightForWidth(w) if popup.hasHeightForWidth() else -1
        if h <= 0:
            h = max(popup.sizeHint().height(), popup.minimumSizeHint().height())
        # (0.3.7 fix: with a word-wrapped text inside, its height for this width is what its layout gives the rows;
        # its minimumSizeHint is not: a Fixed child's minimum is its sizeHint, a wrapped hint's height at another
        # width, which left a band of empty room round the Plotted list's hint)
        popup.setGeometry(x, y, w, h)
        h = popup.height()
        popup.set_notch_x(self._to_overlay(b, QPoint(b.width() // 2, 0)).x() - x)
        plate.setGeometry(x, y + NOTCH_H, w, max(0, h - NOTCH_H))
        self._make_room(y + h)

    def _make_room(self, bottom: int) -> None:
        """The overlay's minimum height: room for a popup that runs past the bottom of its layout (never below the
        layout's own: an explicit minimum smaller than it would let the scroll area squeeze the content)."""
        ov = self._overlay
        need = bottom + POP_ROOM
        lay = ov.layout()
        natural = lay.sizeHint().height() if lay is not None else 0
        if need > natural:
            self._room_set = True
            if ov.minimumHeight() != need:             # (only a change: the new minimum resizes the overlay,
                ov.setMinimumHeight(need)              # which places the popup again)
        else:
            self._give_room_back()

    def _give_room_back(self) -> None:
        if self._room_set:
            self._room_set = False
            try:
                if self._overlay.minimumHeight() != 0:
                    self._overlay.setMinimumHeight(0)
            except RuntimeError:
                pass

    # ---- watchers while open: the grid's ancestors below the overlay, the overlay, the popup
    def _watch(self) -> None:
        self._unwatch()
        if self._current < 0:
            return
        out: List[QWidget] = []
        x = self.parentWidget()
        while x is not None and x is not self._overlay:
            out.append(x)
            x = x.parentWidget()
        out += [self._overlay, self._popups[self._current]]
        for w in out:
            w.installEventFilter(self)
        self._watched = out

    def _unwatch(self) -> None:
        for w in self._watched:
            try:
                w.removeEventFilter(self)
            except RuntimeError:
                pass
        self._watched = []

    def eventFilter(self, obj, ev) -> bool:
        cur = self._current
        if cur < 0:
            return False
        et = ev.type()
        if obj is self._popups[cur]:
            if et == QEvent.Type.LayoutRequest:        # its height changed: a hint shown, the list refilled
                self._place()
        elif obj is self._overlay:
            if et == QEvent.Type.Resize:
                self._place()
        elif et in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            self._place()
        elif et == QEvent.Type.Hide:                   # its section closing
            self.close_popup()
        elif et == QEvent.Type.ParentChange:
            self._watch()
        return False

    def _app_event(self, obj, ev) -> bool:
        """The application filter's events (_PressWatcher): a press outside the popup and its button closes it and
        goes on (not one on the panel's own scroll bar: _scrolls_overlay); Esc closes it while the focus is the
        panel's (_esc_is_ours) and no drop-down list or menu is open."""
        if self._current < 0:
            return False
        et = ev.type()
        if et in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            if isinstance(obj, QWidget) and not (_within(obj, self._popups[self._current])
                                                 or _within(obj, self._buttons[self._current])
                                                 or self._scrolls_overlay(obj)):
                self.close_popup()
            return False                               # (the press goes on: another button opens at once)
        if ev.key() != Qt.Key.Key_Escape or ev.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        if QApplication.activePopupWidget() is not None:       # (an open list or menu closes itself first)
            return False
        if not self._esc_is_ours(QApplication.focusWidget()):  # (Esc on the map cancels a map tool)
            return False
        if et == QEvent.Type.ShortcutOverride:
            ev.accept()                                # no QGIS shortcut takes it
        else:
            self.close_popup()
        return True

    def _scrolls_overlay(self, w: QWidget) -> bool:
        """`w` is a scroll bar of the scroll area holding the overlay (0.3.7 fix): pressing or dragging the panel's
        own bar scrolls the open popup with the content, as the wheel does (it never closes on a scroll; the mockup's
        does not either). Another scroll area's bar is a press elsewhere."""
        if not isinstance(w, QScrollBar):
            return False
        x = w.parentWidget()                           # (a scroll area keeps its bars in a container of its own)
        while x is not None:
            if isinstance(x, QAbstractScrollArea):
                return x.isAncestorOf(self._overlay)
            if x.isWindow():
                break
            x = x.parentWidget()
        return False

    def _esc_is_ours(self, fw: Optional[QWidget]) -> bool:
        """The focus is in the overlay (the popup included), or on the panel around it: a mouse click on an option
        button (TabFocus) gives Qt's click focus to the scroll area holding the content. Never elsewhere in its window
        (the map canvas)."""
        if fw is None:
            return False
        return _within(fw, self._overlay) or (not fw.isWindow() and fw.isAncestorOf(self._overlay))

    # ---- events
    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._reflow()
        if self._current >= 0:
            self._place()

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        if self._current >= 0:
            self._place()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._reflow()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self.close_popup()

    def event(self, e) -> bool:
        et = e.type()
        out = super().event(e)
        if self._current >= 0:
            if et == QEvent.Type.ParentChange:
                self._watch()
            elif et == QEvent.Type.LayoutRequest:
                self._place()
        return out


# ---------------------------------------------------------------- layer cards and the Flare join (0.3.6, D4, D5)
def _band(L: float, T: float, B: float, R: float, s: float, r: float, close: bool = True) -> QPainterPath:
    """The open band's outline: from the rail s above the band, a concave swoop down to (L + s, T), along the top,
    round the top-right and bottom-right corners, back along the bottom and a swoop down to the rail s below it."""
    path = QPainterPath(QPointF(L, T - s))                          # on the rail, s above the band
    path.arcTo(QRectF(L, T - 2 * s, 2 * s, 2 * s), 180, 90)        # concave swoop down to (L + s, T)
    path.lineTo(R - r, T)
    path.arcTo(QRectF(R - 2 * r, T, 2 * r, 2 * r), 90, -90)         # top-right corner
    path.lineTo(R, B - r)
    path.arcTo(QRectF(R - 2 * r, B - 2 * r, 2 * r, 2 * r), 0, -90)  # bottom-right corner
    path.lineTo(L + s, B)
    path.arcTo(QRectF(L, B, 2 * s, 2 * s), 90, 90)                 # concave swoop down to (L, B + s)
    if close:
        path.closeSubpath()                                         # back up along the rail
    return path


def paint_flare(p: QPainter, t: Theme, L: float, T: float, B: float, R: float, rule_y: Optional[float] = None) -> None:
    """One open band (D5, "Flare") painted by a SectionBody: `L` the rail's right edge, `T` / `B` the band's top /
    bottom (B exclusive), `R` its right edge (exclusive), in the body's coordinates; `rule_y` the row of the tabs'
    rule across the band. The band and its swoops in row_open; the rail beside it light blue (row_rail), fading from
    and back to navy over SWOOP px above and below; the 1 px band_line outline along the top, right and bottom edges,
    round both swoops (never on the rail side)."""
    s, r = float(SWOOP), float(BAND_RADIUS)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.fillPath(_band(L, T, B, R, s, r), t.row_open)                  # 1. the band and its two swoops
    p.fillRect(QRectF(L - RAIL_W, T, RAIL_W, B - T), t.row_rail)     # 2. the rail beside it: light blue,
    g = QLinearGradient(0, T - s, 0, T)
    g.setColorAt(0, t.bar)
    g.setColorAt(1, t.row_rail)
    p.fillRect(QRectF(L - RAIL_W, T - s, RAIL_W, s), g)              #    fading in from navy above
    g = QLinearGradient(0, B, 0, B + s)
    g.setColorAt(0, t.row_rail)
    g.setColorAt(1, t.bar)
    p.fillRect(QRectF(L - RAIL_W, B, RAIL_W, s), g)                  #    and back to navy below
    if rule_y is not None:                                           # 3. the tabs' rule, across the band
        p.fillRect(QRectF(L, rule_y, R - L, 1), t.field_line)
    p.setPen(QPen(t.band_line, 1.0))                                 # 4. the 1 px outline, half a pixel in, round
    p.setBrush(Qt.BrushStyle.NoBrush)                                #    both swoops, no rail side
    p.drawPath(_band(L, T + .5, B - .5, R - .5, s, r - .5, close=False))
    p.restore()


class _CardHeader(QWidget):
    """A LayerCard's header: a left click anywhere on it that no child took (the lead check box, the colour button,
    the badge and the ⋯ button take theirs) opens or closes the row (the mockup's row click)."""

    clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            e.accept()
            self.clicked.emit()
            return
        super().mouseReleaseEvent(e)


class LayerCard(QFrame):
    """A layer row of Surfaces, Explorations or Other features (0.3.6): closed, a small card (1 px field_line border,
    row_rail on hover, radius CARD_RADIUS, field fill); open, its header and editor are one band joined to the
    section's rail (Flare), painted by the SectionBody that watches it; the card itself paints nothing then."""

    editorToggled = pyqtSignal(bool)
    checksChanged = pyqtSignal()       # its badge appeared, went or changed its text (set_check)
    LEAD_W, MENU_W = 14, 22            # the lead (check box) and ⋯ columns, kept when a row has neither

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._hover = False
        self._first = False
        self._last = False
        self._after_open = False
        self._gaps = (0, 0)
        self._check = (False, "")      # (badge shown, its text)
        self._check_line = ""
        self.card_layout = QVBoxLayout(self)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(0)
        self.header = _CardHeader(self)
        self._grid = QGridLayout(self.header)
        self._grid.setContentsMargins(7, 6, 7, 6)
        self._grid.setHorizontalSpacing(6)
        self._grid.setVerticalSpacing(2)
        self.badge = CheckBadge(self.header)
        self.badge.hide()
        self.problem_label = ElidedLabel("", parent=self.header)
        self.problem_label.setObjectName("xsProblemLine")
        self.problem_label.setFont(_px_font(self.problem_label.font(), 11.0))
        self.problem_label.setAmber(True)
        self.problem_label.hide()
        self.editor = QFrame(self)
        self.editor.hide()
        self.card_layout.addWidget(self.header)
        self.card_layout.addWidget(self.editor)
        self.header.clicked.connect(self.toggle_editor)
        self.badge.actionTriggered.connect(self._on_card_action)

    # ---- header
    def _place_header(self, lead: Optional[QWidget], icon: Optional[QWidget], name_area: QWidget,
                      menu: Optional[QWidget]) -> None:
        """Put the subclass's header widgets in place: the lead (a 14 px check box; None: a 14 px gap), the 22 x 16
        icon, the name area (stretching), the badge, the ⋯ button (None: a 22 px gap); the problem line under them."""
        g = self._grid
        center = Qt.AlignmentFlag.AlignVCenter

        def gap(w: int) -> QWidget:
            # an empty widget, not a spacer item: the grid puts no spacing beside an empty item, so the Ground row's
            # name would sit 6 px left of the surface rows' (the mockup: one column of names)
            x = QWidget(self.header)
            x.setFixedSize(w, 1)
            return x
        g.addWidget(gap(self.LEAD_W) if lead is None else lead, 0, 0, center)
        if icon is not None:
            g.addWidget(icon, 0, 1, center)
        g.addWidget(name_area, 0, 2)
        g.addWidget(self.badge, 0, 3, center)
        g.addWidget(gap(self.MENU_W) if menu is None else menu, 0, 4, center)
        g.addWidget(self.problem_label, 1, 2, 1, 3)
        g.setColumnStretch(2, 1)
        for lab in name_area.findChildren(ElidedLabel, options=Qt.FindChildOption.FindDirectChildrenOnly):
            lab.setLineHeight(LINE_HEIGHT)    # the name and the subtitle: 15 + 13 px, a 40 px card

    # ---- editor
    def editor_open(self) -> bool:
        return not self.editor.isHidden()

    def set_editor_open(self, on: bool) -> None:
        on = bool(on)
        changed = on != self.editor_open()
        self.editor.setVisible(on)
        lab = getattr(self, "name_label", None)
        if isinstance(lab, ElidedLabel):
            lab.setBold(on)
        self._sync_margins()
        if changed:
            self.editorToggled.emit(on)

    def toggle_editor(self) -> None:
        self.set_editor_open(not self.editor_open())

    # ---- the band's gaps (link_cards)
    def set_first(self, on: bool) -> None:
        self._first = bool(on)
        self._sync_margins()

    def set_last(self, on: bool) -> None:
        self._last = bool(on)
        self._sync_margins()

    def set_after_open(self, on: bool) -> None:
        """The card just above this one in its list is open (two open bands: 12 px apart, swoops overlapping)."""
        self._after_open = bool(on)
        self._sync_margins()

    def _sync_margins(self) -> None:
        if self.editor_open():
            top = 0 if self._after_open else (BAND_GAP - 4 if self._first else BAND_GAP)
            bottom = 0 if self._last else BAND_GAP
        else:
            top = bottom = 0
        if (top, bottom) != self._gaps:
            self._gaps = (top, bottom)
            self.card_layout.setContentsMargins(0, top, 0, bottom)
        self.update()

    def gaps(self) -> Tuple[int, int]:
        """(above, below): the room kept free for the band's swoops while open."""
        return self._gaps

    def band_rect(self) -> QRect:
        """The band in the card's coordinates (its whole rect while closed)."""
        if not self.editor_open():
            return self.rect()
        top, bottom = self._gaps
        return self.rect().adjusted(0, top, 0, -bottom)

    def rule_y(self) -> Optional[int]:
        """The row of a rule across the band (an exploration row's tabs), in the card's coordinates; None: none."""
        return None

    # ---- checks
    def set_check(self, problems: Sequence[Problem] = (), guess: Optional[CardInfo] = None) -> None:
        """The badge (the problems' count, else "check" for a guess) and the problem line (the first problem's line
        and " · +N more"; every line in its tooltip); checksChanged when the badge appeared, went or changed."""
        problems = list(problems or ())
        blocks = [p.card for p in problems] + ([guess] if guess is not None else [])
        has = bool(blocks)
        text = str(sum(int(p.count) for p in problems)) if problems else ("check" if guess is not None else "")
        self.badge.blocks = blocks
        self.badge.actions = card_actions(blocks)
        if text:
            self.badge.set_check_text(text)
        self.badge.setVisible(has)
        line = ""
        if problems:
            line = problems[0].line + (f" · +{len(problems) - 1} more" if len(problems) > 1 else "")
        self._check_line = line
        self.problem_label.setText(line)
        self.problem_label.setToolTip("\n".join(p.line for p in problems))
        self.problem_label.setVisible(bool(problems))
        state = (has, text)
        if state != self._check:
            self._check = state
            self.checksChanged.emit()

    def has_check(self) -> bool:
        return self._check[0]

    def check_text(self) -> str:
        """The problem line ("" for none)."""
        return self._check_line

    def _on_card_action(self, key: str) -> None:
        """A card button of this row's badge (open_layer, open_depths, open_water, looks_right, open)."""

    # ---- look
    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e) -> None:
        if self.editor_open():
            return
        t = theme_for(self.palette())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(t.row_rail if self._hover else t.field_line, 1.0))
        p.setBrush(t.field)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), CARD_RADIUS, CARD_RADIUS)
        p.end()


def link_cards(cards: Sequence[LayerCard]) -> None:
    """Space a list of cards for their bands (after every add, move, remove and editorToggled): the first and the
    last, and whether the card above each one is open."""
    n = len(cards)
    for i, c in enumerate(cards):
        c.set_first(i == 0)
        c.set_last(i == n - 1)
        c.set_after_open(i > 0 and cards[i - 1].editor_open())


class _Tab(QWidget):
    """One tab of a RowTabs (painted from its RowTabs' state; the RowTabs takes its clicks and tooltips)."""

    def __init__(self, text: str, tabs: "RowTabs", index: int):
        super().__init__(tabs)
        self._text = text
        self._tabs = tabs
        self.index = index
        self.setAccessibleName(text)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedHeight(TAB_H)

    def text(self) -> str:
        return self._text

    def _font(self) -> QFont:
        return self._tabs._tab_font(self.index == self._tabs.currentIndex())

    def sizeHint(self) -> QSize:
        return QSize(QFontMetrics(self._font()).horizontalAdvance(self._text) + 18, TAB_H)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _e) -> None:
        tabs = self._tabs
        i = self.index
        t = theme_for(self.palette())
        current = i == tabs.currentIndex()
        if current or i == tabs._hover:
            color = t.ink
        elif tabs.isTabDimmed(i):
            color = _mix(t.muted, t.row_open, 0.45)
        else:
            color = t.muted
        p = QPainter(self)
        p.setFont(self._font())
        p.setPen(color)
        h = self.height()
        p.drawText(QRectF(9.0, 6.0, self.width() - 18.0, h - 11.0),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter), self._text)
        if current:
            p.fillRect(QRect(0, h - 2, self.width(), 2), t.link)
            if tabs.hasFocus():
                p.setPen(QPen(t.ink, 1, Qt.PenStyle.DotLine))
                p.drawRect(QRect(3, 3, self.width() - 7, h - 8))
        p.end()


class RowTabs(QWidget):
    """The tabs of an exploration row's editor (0.3.6): text tabs from x = 7 (under the row's check box); the current
    one ink and DemiBold over a 2 px `link` underline; a dimmed tab (no fields of its kind) muted at 55 %, still
    clickable, with a tooltip. RowTabs paints the 1 px field_line rule along its own bottom row; the section body
    paints the same rule across the whole band (paint_flare's rule_y), so it reaches the rail."""

    currentChanged = pyqtSignal(int)
    X0 = 7

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("xsRowTabs")
        self._tabs: List[_Tab] = []
        self._dimmed: List[bool] = []
        self._tips: List[str] = []
        self._current = -1
        self._hover = -1
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(self.X0, 0, 0, 0)
        self._lay.setSpacing(0)
        self._lay.addStretch(1)
        self.setFixedHeight(TAB_H)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def _tab_font(self, current: bool) -> QFont:
        return _px_font(self.font(), 11.5, QFont.Weight.DemiBold if current else QFont.Weight.Normal)

    # ---- tabs
    def addTab(self, text: str) -> int:
        i = len(self._tabs)
        tab = _Tab(text, self, i)
        self._tabs.append(tab)
        self._dimmed.append(False)
        self._tips.append("")
        self._lay.insertWidget(i, tab)
        if self._current < 0:
            self._current = 0
        self._refresh()
        return i

    def count(self) -> int:
        return len(self._tabs)

    def tabText(self, i: int) -> str:
        return self._tabs[i].text() if 0 <= i < len(self._tabs) else ""

    def tabRect(self, i: int) -> QRect:
        return self._tabs[i].geometry() if 0 <= i < len(self._tabs) else QRect()

    def currentIndex(self) -> int:
        return self._current

    def setCurrentIndex(self, i: int) -> None:
        i = int(i)
        if not 0 <= i < len(self._tabs) or i == self._current:
            return
        self._current = i
        self._refresh()
        self.currentChanged.emit(i)

    def setTabDimmed(self, i: int, on: bool, tip: str = "") -> None:
        if not 0 <= i < len(self._tabs):
            return
        self._dimmed[i] = bool(on)
        self._tips[i] = tip if on else ""
        self._tabs[i].setToolTip(self._tips[i])
        self._tabs[i].update()

    def isTabDimmed(self, i: int) -> bool:
        return self._dimmed[i] if 0 <= i < len(self._dimmed) else False

    def tabToolTip(self, i: int) -> str:
        return self._tips[i] if 0 <= i < len(self._tips) else ""

    def tabAt(self, pos: QPoint) -> int:
        for i, tab in enumerate(self._tabs):
            if tab.geometry().contains(pos):
                return i
        return -1

    def _refresh(self) -> None:
        for tab in self._tabs:
            tab.updateGeometry()
            tab.update()
        self.update()

    # ---- events
    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            i = self.tabAt(e.position().toPoint())
            if i >= 0:
                e.accept()
                self.setCurrentIndex(i)
                return
        super().mouseReleaseEvent(e)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.tabAt(e.position().toPoint()) >= 0:
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        i = self.tabAt(e.position().toPoint())
        if i != self._hover:
            self._hover = i
            self._refresh()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e) -> None:
        if self._hover != -1:
            self._hover = -1
            self._refresh()
        super().leaveEvent(e)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Left:
            self.setCurrentIndex(max(0, self._current - 1))
            return
        if e.key() == Qt.Key.Key_Right:
            self.setCurrentIndex(min(len(self._tabs) - 1, self._current + 1))
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e) -> None:
        super().focusInEvent(e)
        self._refresh()

    def focusOutEvent(self, e) -> None:
        super().focusOutEvent(e)
        self._refresh()

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.ToolTip:
            i = self.tabAt(e.pos())
            tip = self.tabToolTip(i)
            if tip:
                QToolTip.showText(e.globalPos(), tip, self, self.tabRect(i))
            else:
                QToolTip.hideText()
                e.ignore()
            return True
        return super().event(e)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(QRect(0, self.height() - 1, self.width(), 1), theme_for(self.palette()).field_line)
        p.end()


# ---------------------------------------------------------------- surfaces
STYLE_WORDS = {"solid": "solid", "dash": "dashed", "dot": "dotted"}
SURFACE_UNITS = [("Auto", "auto"), ("Feet", "ft"), ("US survey feet", "ftUS"), ("Meters", "m")]


def _narrow_combo(combo: QComboBox, chars: int = 6) -> None:
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(chars)
    combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)


class SurfaceRow(LayerCard):
    """One other surface in the Surfaces list (0.3.6: a LayerCard): [visible] [color] [name / "layer · band · style ·
    mode"] [⋯], and under it an editor that opens on a click on the row. value() is a dict with every key of
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

        line = self.header
        self.visible_box = QCheckBox(line)
        self.visible_box.setToolTip("Draw this surface")
        self.color_btn = QgsColorButton(line)
        self.color_btn.setShowMenu(False)
        self.color_btn.setAllowOpacity(False)
        self.color_btn.setColorDialogTitle("Surface line color")
        self.color_btn.setFixedSize(22, 16)
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
        self.menu_btn.setFixedSize(22, 20)
        self.menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.menu_btn)
        self.act_up = menu.addAction("Move up")
        self.act_down = menu.addAction("Move down")
        menu.addSeparator()
        self.act_remove = menu.addAction("Remove")
        self.menu_btn.setMenu(menu)
        self._place_header(self.visible_box, self.color_btn, self.name_area, self.menu_btn)

        self.editor.setObjectName("xsSurfaceEditor")
        ed = QVBoxLayout(self.editor)
        ed.setContentsMargins(9, 8, 8, 11)
        ed.setSpacing(8)
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

    # ---- editor (editor_open, set_editor_open, toggle_editor: LayerCard's)
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


# ---------------------------------------------------------------- drop-downs (0.3.7, D8 and its amendment)
class ElidedComboBox(QComboBox):
    """A drop-down whose closed box ends its text with "…" when it is too narrow (0.3.7, D8; Fusion clips it), whose
    tooltip is the current item's ToolTipRole data or else its full text (or a lead tip of its own, setLeadTip), and
    whose list is wide enough for its items."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._lead = ""                    # setLeadTip: a tooltip of its own instead of the item's text
        self.currentIndexChanged.connect(self.syncTip)

    def fullText(self) -> str:
        """The text to paint before eliding (SheetSizeCombo: its own)."""
        return self.currentText()

    def setLeadTip(self, tip: str) -> None:
        """A tooltip of its own (0.3.7 fix: Tops from keeps its 0.3.6 tooltip): shown alone while the box shows its
        text whole, with the full text under it while the box shows it cut (the 260 px dock)."""
        self._lead = str(tip or "")
        self.syncTip()

    def _option(self) -> QStyleOptionComboBox:
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        return opt

    def _room(self, opt: QStyleOptionComboBox) -> int:
        """The width the style gives the label (CE_ComboBoxLabel: the edit field less 1 px each side, less the
        icon)."""
        r = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, opt, QStyle.SubControl.SC_ComboBoxEditField,
                                        self)
        room = r.width() - 2
        if not opt.currentIcon.isNull():
            room -= self.iconSize().width() + 4
        return max(0, room)

    def displayText(self) -> str:
        """The text as painted now (fullText() elided to the room)."""
        return self.fontMetrics().elidedText(self.fullText(), Qt.TextElideMode.ElideRight, self._room(self._option()))

    def syncTip(self, *_args) -> None:
        """The tooltip again (also after setItemData(..., ToolTipRole)); with a lead tip, it and, while the shown box
        cuts the text, the full text."""
        if self._lead:
            cut = self.isVisible() and self.displayText() != self.fullText()
            self.setToolTip(f"{self._lead}\n{self.fullText()}" if cut else self._lead)
            return
        i = self.currentIndex()
        tip = self.itemData(i, Qt.ItemDataRole.ToolTipRole) if i >= 0 else None
        self.setToolTip(str(tip) if tip else self.currentText())

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self._lead:                     # (cut or whole: the width decides)
            self.syncTip()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self._lead:
            self.syncTip()

    def paintEvent(self, _e) -> None:
        # (QComboBox's own paintEvent with the label's text elided)
        p = QStylePainter(self)
        p.setPen(self.palette().color(QPalette.ColorRole.Text))
        opt = self._option()
        p.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)
        text = self.fullText()
        if not text and self.currentIndex() < 0 and self.placeholderText():
            opt.palette.setBrush(QPalette.ColorRole.ButtonText, opt.palette.placeholderText())
            text = self.placeholderText()
        opt.currentText = self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, self._room(opt))
        p.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, opt)
        p.end()

    def showPopup(self) -> None:
        v = self.view()
        v.setMinimumWidth(min(360, max(self.width(), v.sizeHintForColumn(0) + 2 * v.frameWidth() + 20)))
        super().showPopup()


class _SizeRow(QWidget):
    """One row of the Size list (0.3.7): its check box (the name), a stretch and the muted detail ("8.5 × 11 in"),
    SIZE_ROW_H high; the theme's hover fill while hovered; a click anywhere on the row toggles the box (the mockup's
    label)."""

    def __init__(self, key: str, name: str, detail: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.key = str(key)
        self._hover = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(SIZE_ROW_H)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 3, 10, 3)
        lay.setSpacing(7)
        self.box = QCheckBox(str(name), self)
        self.box.setFont(_px_font(self.box.font(), 11.5))
        self.detail = QLabel(str(detail), self)
        self.detail.setObjectName("xsMuted")
        self.detail.setFont(_px_font(self.detail.font(), 10.5))
        lay.addWidget(self.box, 0)
        lay.addStretch(1)
        lay.addWidget(self.detail, 0)

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            e.accept()                     # (the release toggles the box)
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            e.accept()
            self.box.click()               # (his click: the box's clicked)
            return
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e) -> None:
        if self._hover and self.isEnabled():
            p = QPainter(self)
            p.fillRect(self.rect(), theme_for(self.palette()).hover)
            p.end()


class _SizeList(QFrame):
    """SheetSizeCombo's open list (0.3.7, the mockup's round-8 .sizepop): a Popup window of its own whose parent is
    the combo (the panel's stylesheet reaches it; WA_WindowPropagation: its palette and font too). Inside it one frame,
    `box` (QFrame#xsSizeList: the stylesheet's field background and field_line border; a stylesheet gives a window no
    background or border of its own, its child frame it does), holding a _SizeRow per sheet size, a rule, the custom
    row and the muted foot line. Qt closes it as any popup (a press outside it, Esc); a press on the combo itself
    closes it without the press being replayed to the combo, which would open it again (WA_NoMouseReplay, as Qt's own
    combo list does). 0.3.7 finish: the box and foot rules are also its own stylesheet (_apply_theme): under an
    application stylesheet (Night Mapping, Blend of Gray) the panel's alone gave the foot no padding and the box no
    border inset, its text edge to edge."""

    def __init__(self, combo: QComboBox, sizes: Sequence[Tuple[str, str, str]], custom: Tuple[str, str, str],
                 foot: str):
        super().__init__(combo, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("xsSizeListPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_WindowPropagation, True)
        self._combo = combo
        self._in_theme = False                        # setting its stylesheet (_apply_theme)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.box = QFrame(self)
        self.box.setObjectName("xsSizeList")
        outer.addWidget(self.box)
        lay = QVBoxLayout(self.box)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(0)
        self.rows: List[_SizeRow] = []
        for key, name, detail in sizes:
            row = _SizeRow(key, name, detail, self.box)
            lay.addWidget(row)
            self.rows.append(row)
        self.rule_box = QWidget(self.box)
        rl = QVBoxLayout(self.rule_box)
        rl.setContentsMargins(8, 4, 8, 4)
        rl.setSpacing(0)
        rl.addWidget(_Rule(1, self.rule_box, "rule"))
        lay.addWidget(self.rule_box)
        self.custom_row = _SizeRow(custom[0], custom[1], custom[2], self.box)
        lay.addWidget(self.custom_row)
        lay.addSpacing(4)
        self.foot = QLabel(str(foot), self.box)
        self.foot.setObjectName("xsSizeFoot")
        self.foot.setTextFormat(Qt.TextFormat.PlainText)
        self.foot.setWordWrap(True)
        self.foot.setFont(_px_font(self.foot.font(), 10.5))
        self.foot.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.foot)
        self.foot.setVisible(bool(foot))

    def popup(self) -> None:
        """Show it under the combo (above it when the screen has no room below; with room on neither side, on the
        side with more, kept on the screen), at least SIZE_LIST_W wide, the focus on the first box."""
        combo = self._combo
        w = max(SIZE_LIST_W, combo.width())
        self._apply_theme()
        self.ensurePolished()              # (the foot's stylesheet padding counts in its height)
        self.setFixedWidth(w)
        self.layout().activate()
        h = self.heightForWidth(w) if self.hasHeightForWidth() else self.sizeHint().height()
        h = max(h, self.minimumSizeHint().height())
        self.setFixedHeight(h)
        avail = self._available()
        pt = combo.mapToGlobal(QPoint(0, combo.height() + 2))
        y = pt.y()
        if y + h > avail.bottom() + 1:                 # no room below: above it when the screen has room there
            above = combo.mapToGlobal(QPoint(0, -h - 2)).y()
            if above >= avail.top():
                y = above
            else:
                # neither (a short screen; 0.3.7 fix): the side with more room, moved up or down to stay on the
                # screen (its top kept on it when the screen is shorter than the list)
                top = combo.mapToGlobal(QPoint(0, 0)).y()
                if top - avail.top() > avail.bottom() + 1 - (top + combo.height()):
                    y = above
                y = max(avail.top(), min(y, avail.bottom() + 1 - h))
        x = max(avail.left(), min(pt.x(), avail.right() + 1 - w))
        self.move(x, y)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay, False)
        self.show()
        if self.rows:
            self.rows[0].box.setFocus(Qt.FocusReason.PopupFocusReason)

    def _available(self) -> QRect:
        """The screen's room for the list, around the combo (tests stand in a short screen)."""
        screen = self._combo.screen() or QApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else QRect(0, 0, 100000, 100000)

    def _apply_theme(self) -> None:
        """Its own stylesheet, _size_list_rules in its palette's colours: set when it changes (as CheckCard's)."""
        sheet = _size_list_rules(theme_for(self.palette()))
        if sheet == self.styleSheet():
            return
        self._in_theme = True
        try:
            self.setStyleSheet(sheet)
        finally:
            self._in_theme = False

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        # (open: its colours follow the palette; not the palette changes its own stylesheet brings)
        if e.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange) and not self._in_theme \
                and self.isVisible():
            self._apply_theme()

    def mousePressEvent(self, e) -> None:
        # (QWidget's own closes a popup on a press outside it; a press on the combo is not replayed to it)
        combo = self._combo
        on_combo = (not self.rect().contains(e.position().toPoint())
                    and QRect(combo.mapToGlobal(QPoint(0, 0)), combo.size()).contains(e.globalPosition().toPoint()))
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay, on_combo)
        super().mousePressEvent(e)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):         # (Esc: QWidget's own, for a popup)
            self.close()
            return
        super().keyPressEvent(e)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._combo.update()               # (the arrow's open state)

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._combo.update()


class SheetSizeCombo(ElidedComboBox):
    """Scale & sheet › Size (0.3.7, the amendment of D8): a drop-down whose list has a check box per sheet size, a
    rule, an exclusive "custom" item and a muted foot line; the list stays open while he checks (a press outside it,
    Esc, or a press on the box again closes it). The closed box paints fullText() (elided), its tooltip is the second
    text of `describe`. It holds no items of its own (count() 0): the list is its own window (_SizeList)."""

    checksChanged = pyqtSignal()                     # his change (a box clicked), or setChecks(..., emit=True)

    def __init__(self, sizes: Sequence[Tuple[str, str, str]], custom: Tuple[str, str, str], foot: str,
                 describe: Callable[[List[str], bool], Tuple[str, str]], parent: Optional[QWidget] = None):
        # sizes / custom: (key, name, detail), e.g. ("letter", "Letter", "8.5 × 11 in"), ("custom", "Custom", "cut to
        # the drawing"); describe(checked keys, custom) -> (closed text, tooltip)
        super().__init__(parent)
        self.setObjectName("xsSheetSize")
        self._describe = describe
        self._keys = [str(k) for k, _name, _detail in sizes]
        self._custom = str(custom[0])
        self._list = _SizeList(self, sizes, custom, foot)
        self._boxes: Dict[str, QCheckBox] = {}
        for row in self._list.rows + [self._list.custom_row]:
            self._boxes[row.key] = row.box
            row.box.clicked.connect(lambda _checked=False, k=row.key: self._on_clicked(k))
        _narrow(self)
        self._sync()

    # ---- the checks
    def checked(self) -> List[str]:
        """The checked size keys, in list order ([] while custom)."""
        return [k for k in self._keys if self._boxes[k].isChecked()]

    def isCustom(self) -> bool:
        return self._boxes[self._custom].isChecked()

    def setChecks(self, keys: Iterable[str], custom: bool = False, emit: bool = False) -> None:
        """Check exactly `keys` (unknown keys ignored), or custom alone (custom wins); silent unless `emit`."""
        want = set() if custom else {str(k) for k in keys}
        for k in self._keys:
            self._set_box(k, k in want)
        self._set_box(self._custom, bool(custom))
        self._sync()
        if emit:
            self.checksChanged.emit()

    def _set_box(self, key: str, on: bool) -> None:
        b = self._boxes[key]
        if b.isChecked() != bool(on):
            was = b.blockSignals(True)
            b.setChecked(bool(on))
            b.blockSignals(was)

    def _on_clicked(self, key: str) -> None:
        if self._boxes[key].isChecked():               # custom clears the sizes, a size clears custom
            if key == self._custom:
                for k in self._keys:
                    self._set_box(k, False)
            else:
                self._set_box(self._custom, False)
        self._sync()                                   # (unchecking the last leaves none: describe says what then)
        self.checksChanged.emit()

    def _sync(self) -> None:
        self.syncTip()
        self.setAccessibleDescription(self.fullText())
        self.update()

    # ---- the closed box
    def fullText(self) -> str:
        return self._describe(self.checked(), self.isCustom())[0]

    def syncTip(self, *_args) -> None:
        self.setToolTip(wrap_tip(self._describe(self.checked(), self.isCustom())[1]))

    def _option(self) -> QStyleOptionComboBox:
        opt = super()._option()
        if self._list.isVisible():
            opt.state |= QStyle.StateFlag.State_On
        return opt

    # ---- the list (tests read boxes and list_frame)
    def boxes(self) -> Dict[str, QCheckBox]:
        """Key -> its check box, the custom key included."""
        return dict(self._boxes)

    def list_frame(self) -> QFrame:
        """The open list (hidden while closed)."""
        return self._list

    def showPopup(self) -> None:
        # (no super(): its own list, not the item view; QComboBox's click, Space, F4 and Alt+Down call this)
        self._list.popup()

    def hidePopup(self) -> None:
        self._list.hide()


# ---------------------------------------------------------------- small helpers (moved from ui.dock in 0.3.3)
def _combo(items: Sequence[Tuple[str, Any]], parent=None, elide: bool = False) -> QComboBox:
    """A drop-down of (text, data) items that shrinks with the dock; `elide` (0.3.7): an ElidedComboBox."""
    c = ElidedComboBox(parent) if elide else QComboBox(parent)
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


# what a number box lists (0.3.5): number fields and text fields, whose plain numbers are read (core.explorations
# to_number: "642.3", " 642 ", "1,234.5"; anything else is left out and flagged). The box's own field-type icons tell
# them apart. (0.3.4 and before: number fields only, so a CSV's box listed nothing and would not open.)
NUMBER_BOX_FILTERS = QgsFieldProxyModel.Filter.Numeric | QgsFieldProxyModel.Filter.String


def field_kind(field) -> Optional[bool]:
    """A QgsField as ui.point_guess.Fields sees it: True a number field, False a text field, None any other kind (a
    date, a boolean ...), as NUMBER_BOX_FILTERS lists them."""
    if field.isNumeric():
        return True
    return False if field.type() == QMetaType.Type.QString else None


def _field_combo(tooltip: str, numeric: bool = False, allow_empty: bool = True) -> QgsFieldComboBox:
    """A field of a layer (a number box when `numeric`: number and text fields, NUMBER_BOX_FILTERS), or none when
    `allow_empty`."""
    c = QgsFieldComboBox()
    c.setAllowEmptyFieldName(allow_empty)
    if numeric:
        c.setFilters(NUMBER_BOX_FILTERS)
    c.setToolTip(tooltip)
    _narrow(c)
    return c


def _numeric_field_combo(tooltip: str) -> QgsFieldComboBox:
    """A number box of the explorations layer (a number or text field), or none."""
    return _field_combo(tooltip, numeric=True)


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


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# a long tooltip (0.3.7 finish): Qt shows a plain-text one on one line (it wraps one only at the screen's width), and
# wraps a rich-text one, unless its width is set, at about a third of its length (120 to 160 px here)
TIP_W = 240                            # px: the width a long tooltip wraps at (the mockup's tip box: 220)
TIP_MAX = 320                          # px: a tooltip whose longest line is wider than this (QToolTip's font) wraps
_TIP_HEAD = f'<table width="{TIP_W}" cellspacing="0" cellpadding="0"><tr><td>'
_TIP_TAIL = "</td></tr></table>"


def wrap_tip(text: str) -> str:
    """`text` as a tooltip (0.3.7 finish, the panel's 0.3.7 ones): as it is when its longest line fits in TIP_MAX px
    of QToolTip's font, else rich text that Qt wraps at TIP_W px (one cell of a table that wide; its lines kept).
    tip_text() gives the text back."""
    text = str(text or "")
    fm = QFontMetrics(QToolTip.font())
    if text.lstrip().startswith("<") or max(fm.horizontalAdvance(line) for line in text.split("\n")) <= TIP_MAX:
        return text
    return _TIP_HEAD + _esc(text).replace("\n", "<br>") + _TIP_TAIL


def tip_text(tip: str) -> str:
    """A tooltip's text: wrap_tip's undone (tests compare it)."""
    tip = str(tip or "")
    if not (tip.startswith(_TIP_HEAD) and tip.endswith(_TIP_TAIL)):
        return tip
    inner = tip[len(_TIP_HEAD):len(tip) - len(_TIP_TAIL)].replace("<br>", "\n")
    return inner.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _cbox(text: str, tip: str = "", strong: bool = False) -> QCheckBox:
    b = QCheckBox(text)
    b.setToolTip(tip)
    if strong:
        f = QFont(b.font())
        f.setWeight(QFont.Weight.DemiBold)
        b.setFont(f)
    return b


def set_field(combo: QgsFieldComboBox, name: str, guesses: Sequence[str], allow_empty: bool = False,
              numeric: bool = False, keep_empty: bool = False, pk: Iterable[str] = (), text_ok=None) -> bool:
    """Keep `name` if the combo's layer has it, else guess from `guesses` (a number box when `numeric`: number and
    text fields, number fields first, a text field only when `text_ok` says its values are numbers; never the
    primary-key fields `pk`). With `keep_empty` (and `allow_empty`), an empty `name` means none and is kept. Without
    `allow_empty`, a box with no guess takes the first field that is not the primary key (a number field for a number
    box). A number box that gets no field shows none (0.3.5: not the first field QgsFieldComboBox picks by itself,
    often the name column of a CSV; the build then asks him to choose). True when a field was guessed from `guesses`
    (the 0.3.2 rule of the panel's field boxes, ui.point_guess.pick_field)."""
    fields = combo.fields() if combo.layer() is not None else []
    value, guessed = pick_field([(f.name(), field_kind(f)) for f in fields], pk, name, guesses, numeric=numeric,
                                required=not allow_empty, keep_empty=keep_empty and allow_empty, text_ok=text_ok)
    if value or allow_empty or numeric:
        combo.setField(value)
    return guessed
