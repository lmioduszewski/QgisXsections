"""Each exploration's colour from its point layer's own QGIS style (0.3.4, DESIGN.md decision 23).

An exploration row drawn in Color takes, for each exploration, the colour of the symbol the layer's renderer draws
that feature with on the map, whatever the renderer is: one symbol, categories, ranges or rules (data-defined fill
colours too). Only the renderer is read, never changed: the work is done on a clone, so the map is not touched.

The rules, in plain words:
- the colour of a symbol is its fill; a fill that is transparent or white (or nearly: every channel at least
  NEAR_WHITE), or a marker shape that is not filled (a cross, a line), gives its outline colour instead; when neither
  is usable the next symbol layer is tried; a symbol with none is black. Opacity is not drawn.
- single symbol, categorized and graduated styles: the symbol QGIS draws (symbolForFeature) gives the colour. Its
  name in the legend is the legend item of the feature when that item has the drawn colour; otherwise the last item
  of that colour (QGIS draws a NULL or unmatched value with the LAST category whose value is NULL or "", while the
  legend keys name the first).
- rule-based styles (and any other renderer with a legend): the last matching legend item, in the legend's order,
  that has a symbol (the one drawn on top). A rule switched off in the Layers panel matches nothing, and the ELSE
  rule does not take its features either (as QGIS 4.2.1 draws them: not at all).
- every scale range of a rule counts (renderer scale 0): the sheet never depends on the map's zoom. (Categorized and
  graduated styles have no scale ranges and are read at 1:1: at scale 0 they would draw switched-off classes too.)
- point displacement and point cluster renderers are read through the renderer they wrap; a data-defined size legend
  is left out (its size classes are not symbols of the layer).
- a feature the style draws with no symbol (an unticked category, no matching rule, a value outside every range) has
  no colour: the sheet draws it black.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from qgis.core import (QgsApplication, QgsExpressionContext, QgsExpressionContextUtils, QgsFeatureRequest,
                       QgsRenderContext, QgsSimpleMarkerSymbolLayerBase, QgsSymbolLayer)
from qgis.PyQt.QtCore import Qt

from .model import LayerStyle, StyleItem

NEAR_WHITE = 230                  # a colour with every channel at least this is "white" (a hollow marker's fill)
NO_VALUE_LABEL = "(no value)"     # a categorized style's NULL / empty category with no label
OTHER_VALUES_LABEL = "(other values)"   # an ELSE rule, or a catch-all category, with no label
RULE_LABEL_MAX = 40               # a rule without a label is named by its filter, cut to this many characters

_KINDS = {"singleSymbol": "single", "categorizedSymbol": "categorized", "graduatedSymbol": "graduated",
          "RuleRenderer": "rule"}
_WRAPPERS = ("pointDisplacement", "pointCluster")
_COUNTING = ("categorizedSymbol", "graduatedSymbol")     # renderers that count (draw every class) at scale 0
_P = QgsSymbolLayer.Property


def _near_white(c) -> bool:
    return min(c.red(), c.green(), c.blue()) >= NEAR_WHITE


def _dd_color(sl, prop, context: QgsExpressionContext, default):
    """A symbol layer's colour `prop` (FillColor / StrokeColor): its data-defined value when that is active and
    gives a colour, else `default` (a NULL value gives the default too)."""
    props = sl.dataDefinedProperties()
    if props.isActive(prop):
        c, ok = props.valueAsColor(prop, context, default)
        if ok and c.isValid():
            return c
    return default


def _layer_color(sl, context: QgsExpressionContext) -> Optional[str]:
    """The colour one symbol layer draws in ("#rrggbb"), or None when it has no usable one (see symbol_color)."""
    fill = _dd_color(sl, _P.FillColor, context, sl.color())
    filled = fill.isValid() and fill.alpha() > 0
    if filled and isinstance(sl, QgsSimpleMarkerSymbolLayerBase) \
            and not QgsSimpleMarkerSymbolLayerBase.shapeIsFilled(sl.shape()):
        filled = False                                   # a cross, a line ...: only its outline is drawn
    if filled and not _near_white(fill):
        return fill.name()
    try:
        stroke = sl.strokeColor()
    except AttributeError:                               # a symbol layer without an outline
        return None
    try:
        if sl.strokeStyle() == Qt.PenStyle.NoPen:        # an outline that is not drawn
            return None
    except AttributeError:
        pass
    stroke = _dd_color(sl, _P.StrokeColor, context, stroke)
    if stroke.isValid() and stroke.alpha() > 0 and not _near_white(stroke):
        return stroke.name()
    return None


def symbol_color(symbol, context: Optional[QgsExpressionContext] = None) -> str:
    """The colour XSections draws a symbol's explorations in, "#rrggbb": the first enabled symbol layer (in order)
    with a usable colour gives it: its fill (data-defined FillColor when active) when the fill is not transparent,
    not near white (min(r, g, b) >= NEAR_WHITE) and, for a simple marker, of a filled shape; else its outline
    (strokeColor, data-defined StrokeColor when active) when valid, not transparent and not near white; else the
    next layer; none: "#000000". Opacity (alpha) is not drawn."""
    if symbol is None:
        return "#000000"
    ec = context if context is not None else QgsExpressionContext()
    for sl in symbol.symbolLayers():
        if not sl.enabled():
            continue
        c = _layer_color(sl, ec)
        if c is not None:
            return c
    return "#000000"


def _is_null(value) -> bool:
    return value is None or value == "" or (hasattr(value, "isNull") and value.isNull())


def _label(r, kind: str, key: str, label: str, pos: int) -> str:
    """A legend item's name: its own label when it is not blank; else made from the class (section 3.2)."""
    if label and label.strip():
        return label
    if kind == "categorized":
        cats = r.categories()
        cat = next((c for c in cats if c.uuid() == key), None)
        if cat is None and 0 <= pos < len(cats):
            cat = cats[pos]                              # the legend follows the categories' order
        if cat is None:
            return label
        value = cat.value()
        if isinstance(value, (list, tuple)):             # a merged category: its values
            value = ", ".join("" if _is_null(v) else str(v) for v in value)
        return NO_VALUE_LABEL if _is_null(value) else str(value)
    if kind == "graduated":
        ranges = r.ranges()
        rng = next((g for g in ranges if g.uuid() == key), None)
        if rng is None and 0 <= pos < len(ranges):
            rng = ranges[pos]
        return f"{rng.lowerValue():g} - {rng.upperValue():g}" if rng is not None else label
    if kind == "rule":
        rule = r.rootRule().findRuleByKey(key)
        if rule is None:
            return "(rule)"
        if rule.isElse():
            return OTHER_VALUES_LABEL
        text = (rule.filterExpression() or "").strip()
        if not text:
            return "(rule)"
        return text if len(text) <= RULE_LABEL_MAX else text[:RULE_LABEL_MAX - 1] + "…"
    return label or ""


def _kind(r, legend: list) -> Tuple[str, str]:
    """(kind, name) of a renderer (name: kind "other" only)."""
    if not legend:
        return "none", ""
    t = r.type()
    if t in _KINDS:
        return _KINDS[t], ""
    meta = QgsApplication.rendererRegistry().rendererMetadata(t)
    return "other", (meta.visibleName() if meta is not None else "") or t


def _render_scale(r) -> float:
    """The renderer scale of a read. 0 makes every rule's scale range count (rule-based styles), but categorized and
    graduated renderers take a scale of 0 for "counting the features" and then draw switched-off classes too
    (QGIS 4.2.1, checked: an unticked category kept its symbol): those, and a renderer wrapping one, are read at
    1:1, which they draw the same at (they have no scale ranges)."""
    inner = r
    while inner is not None:
        if inner.type() in _COUNTING:
            return 1.0
        inner = inner.embeddedRenderer() if hasattr(inner, "embeddedRenderer") else None
    return 0.0


def _context(layer, project) -> QgsExpressionContext:
    """The expression context of a read: the global, project and layer scopes."""
    if project is not None:
        return QgsExpressionContext([QgsExpressionContextUtils.globalScope(),
                                     QgsExpressionContextUtils.projectScope(project),
                                     QgsExpressionContextUtils.layerScope(layer)])
    return QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(layer))


def read_styles(layer, fids: Sequence[int], project=None) -> Tuple[LayerStyle, Dict[int, Tuple[int, str]]]:
    """layer_style(layer), and for each fid the (index in its items, colour) of the symbol QGIS draws that feature
    with, or (-1, "") when it draws none (an unticked category, no matching rule, a value out of every range).
    The colour is symbol_color of the symbol drawn, for that feature (data-defined colours too): symbolForFeature
    for single / categorized / graduated, the last matching legend item for rule-based (the facts table)."""
    out: Dict[int, Tuple[int, str]] = {int(x): (-1, "") for x in fids}
    renderer = getattr(layer, "renderer", None)
    live = renderer() if renderer is not None else None
    if live is None:
        return LayerStyle("none"), out
    base = live
    while base.type() in _WRAPPERS and base.embeddedRenderer() is not None:
        base = base.embeddedRenderer()
    r = base.clone()                                     # never startRender the layer's own renderer
    if hasattr(r, "setDataDefinedSizeLegend"):
        r.setDataDefinedSizeLegend(None)                 # its size classes are not symbols of the layer (the clone)
    ec = _context(layer, project)
    ctx = QgsRenderContext()
    ctx.setRendererScale(_render_scale(r))               # rule-based: 0, every rule's scale range counts
    ctx.setExpressionContext(ec)
    legend = [(it.ruleKey(), it.label(), it.symbol().clone(), it.isCheckable()) for it in r.legendSymbolItems()
              if it.symbol() is not None]                # (symbols cloned: the items may be freed)
    kind, name = _kind(base, legend)
    items: List[StyleItem] = [
        StyleItem(key, _label(r, kind, key, label, pos), symbol_color(sym, ec),
                  bool(r.legendSymbolItemChecked(key)) if checkable else True)
        for pos, (key, label, sym, checkable) in enumerate(legend)]
    field = r.classAttribute() if kind in ("categorized", "graduated") else ""
    style = LayerStyle(kind=kind, field=field or "", name=name, items=items)
    if not out or not items:
        return style, out
    r.startRender(ctx, layer.fields())
    try:
        for f in layer.getFeatures(QgsFeatureRequest().setFilterFids(list(out))):
            ctx.expressionContext().setFeature(f)
            keys = set(r.legendKeysForFeature(f, ctx))
            m = [i for i, it in enumerate(items) if it.key in keys]
            fid = int(f.id())
            if kind in ("single", "categorized", "graduated"):      # what QGIS draws (the facts table)
                drawn = r.symbolForFeature(f, ctx)
                if drawn is None:
                    continue                                         # (-1, ""): drawn black
                static = symbol_color(drawn, ec)                     # no feature: comparable with StyleItem.color
                same = [i for i, it in enumerate(items) if it.color == static]
                rank = (m[-1] if m and items[m[-1]].color == static
                        else same[-1] if same else m[-1] if m else -1)
                out[fid] = (rank, symbol_color(drawn, ctx.expressionContext()))
            elif m:                                                  # rule-based, other: the last matching item
                out[fid] = (m[-1], symbol_color(legend[m[-1]][2], ctx.expressionContext()))
    finally:
        r.stopRender(ctx)
    return style, out


def layer_style(layer) -> LayerStyle:
    """The layer's style without reading any feature (the row editor; build_section through read_styles): kind,
    class field, the items with a symbol in the legend's order, each with its label (see the label rules), colour
    (symbol_color with no feature) and on (legendSymbolItemChecked for a checkable item, else True). No renderer, or
    no items (heatmap, null symbol): kind "none", no items."""
    return read_styles(layer, [])[0]
