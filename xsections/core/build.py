"""build_section: settings + project -> SectionModel (geometry and data only, no drawing)."""
from __future__ import annotations

import math
import traceback
from typing import Dict, List, Optional

from qgis.core import Qgis, QgsMessageLog, QgsProject, QgsRasterLayer, QgsVectorLayer

from .explorations import find_explorations, nearest_distance_ft, read_wl_table
from .mf6_section import begin_build, model_surface, surface_name
from .model import (LOOK_GRAY, NO_POINTS, Hit, OtherLayerInfo, OtherPoint, PointLayerInfo, SectionError,
                    SectionModel, Settings, SurfaceProfile, clean_hidden, clean_other_points, clean_surfaces,
                    hidden_key, layer_rows, layer_view, line_key, point_legend_name)
from .others import find_other_points
from .section import (azimuth_deg, dem_cell_size_ft, ground_profile, line_vertices, raster_sampler,
                      resolve_line, section_crs, surface_profile, vertex_stations)
from .symbology import read_styles
from .units import distance_factor_to_ft, resolve_z_units

MAX_SAMPLES = 200_000          # ground samples per line; the step grows past this (very long lines)
FAR_FT = 5280.0                # nothing within a mile of the line: hint at a wrong point layer CRS
_Z_NAMES = {"ft": "feet", "ftUS": "US survey feet", "m": "meters"}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _layer_name(project: QgsProject, layer_id: str) -> str:
    """The name of the project layer `layer_id` ("" if there is none)."""
    layer = project.mapLayer(layer_id) if layer_id else None
    return layer.name() if layer is not None else ""


def _look_color(row: dict) -> str:
    """PointLayerInfo.color (and Hit.color) of a row: LOOK_GRAY for gray, else "" (black: render's own colours; color:
    each exploration's colour comes from the layer's style, per hit, read_styles)."""
    return LOOK_GRAY if row["look"] == "gray" else ""


def _point_layers(rows: List[dict], project: QgsProject) -> Dict[int, QgsVectorLayer]:
    """The layer of every exploration row that is on (ticked, with a layer chosen), by row index. A chosen layer
    that is gone or can't be read is an error naming the row (DESIGN.md decision 9: explorations are never quietly
    left out); a row without a layer is skipped."""
    several = sum(1 for r in rows if r["visible"]) > 1
    out: Dict[int, QgsVectorLayer] = {}
    for i, row in enumerate(rows):
        if not (row["visible"] and row["layer_id"]):
            continue
        layer = project.mapLayer(row["layer_id"])
        of = f" of “{row['name'].strip() or f'row {i + 1}'}”" if several else ""
        if not isinstance(layer, QgsVectorLayer):
            raise SectionError(f"The explorations (points) layer{of} is no longer in the project. Choose it again, "
                               "untick its row or remove it.")
        if not layer.isValid():
            raise SectionError(f"The explorations layer {layer.name()}{of} could not be read.")
        out[i] = layer
    return out


def _other_layers(others: List[dict], project: QgsProject, warnings: List[str]) -> Dict[int, QgsVectorLayer]:
    """The layer of every other-points row that is on, by row index. Other points follow the surfaces rule (DESIGN.md
    decision 15): a row whose layer is gone, not a point layer or unreadable is left out with a warning."""
    out: Dict[int, QgsVectorLayer] = {}
    for j, d in enumerate(others):
        if not (d["visible"] and d["layer_id"]):
            continue
        layer = project.mapLayer(d["layer_id"])
        if (not isinstance(layer, QgsVectorLayer) or not layer.isValid()
                or layer.geometryType() != Qgis.GeometryType.Point):
            label = d["name"].strip() or (layer.name() if layer is not None else "") or f"row {j + 1}"
            warnings.append(f"Other points “{label}”: its layer is no longer in the project; left out.")
            continue
        out[j] = layer
    return out


def build_section(settings: Settings, project: Optional[QgsProject] = None) -> SectionModel:
    """Resolve layers by id, sample the ground, project the explorations of every exploration row (layer_rows) and
    the other points. Raises SectionError with a message fit for the panel when something the user can fix is
    missing or wrong."""
    project = project or QgsProject.instance()

    dem = project.mapLayer(settings.dem_layer_id) if settings.dem_layer_id else None
    if not isinstance(dem, QgsRasterLayer):
        raise SectionError("Choose a DEM (ground surface raster).")
    if not dem.isValid():
        raise SectionError(f"The DEM {dem.name()} could not be read.")
    band = int(settings.dem_band or 1)
    if band < 1 or band > dem.bandCount():
        raise SectionError(f"The DEM {dem.name()} has no band {band}.")

    # exploration rows are optional: without any the sheet shows the ground line (and any other points) only
    rows = layer_rows(settings)
    layers = _point_layers(rows, project)
    others = clean_other_points(settings.other_points)
    gone: List[str] = []                                 # other-points rows left out (warnings, in row order)
    other_layers = _other_layers(others, project, gone)

    crs = section_crs(dem, project)
    dist_factor = distance_factor_to_ft(crs)
    line = resolve_line(settings, project, crs)
    vstations = vertex_stations(line, dist_factor)
    length = vstations[-1]
    if not length > 0:
        raise SectionError("The section line has no length.")

    ctx = project.transformContext()
    z_units, z_factor, z_how = resolve_z_units(dem, settings.dem_z_units, band)
    sampler = raster_sampler(dem, band, crs, z_factor, ctx)
    cell = dem_cell_size_ft(dem, crs, dist_factor, ctx)
    step = cell if math.isfinite(cell) and cell > 0 else length / 1000.0
    step = max(step, length / MAX_SAMPLES)
    ground = ground_profile(line, sampler, step, dist_factor)
    if ground.coverage <= 0.0:
        raise SectionError(
            f"The section line does not cross the DEM ({dem.name()}): no ground data anywhere along it. "
            "Check the line and the DEM.")

    warnings: List[str] = []
    surfaces = build_surfaces(settings, project, line, crs, dist_factor, length, warnings)

    # --- explorations, row by row (each row reads its own fields through layer_view; the rules stay shared).
    #     Everything chosen is plotted (no de-duplication between rows), except what he left off on this line.
    lk = line_key(settings)
    hidden = set(clean_hidden(settings.hidden_points))
    several = sum(1 for r in rows if r["visible"]) > 1
    wl_cache: Dict[tuple, dict] = {}                     # a water-level table shared by rows is read once
    wl_warnings: Dict[tuple, str] = {}                   # its levels that are not numbers: one per table field
    views: Dict[int, Settings] = {}
    infos: List[PointLayerInfo] = []
    hits: List[Hit] = []
    left_off: List[Hit] = []
    beyond: List[str] = []
    near_count = 0
    for i, row in enumerate(rows):
        layer = layers.get(i)
        layer_name = layer.name() if layer is not None else _layer_name(project, row["layer_id"])
        info = PointLayerInfo(index=i, layer_id=row["layer_id"], name=point_legend_name(row, layer_name)
                              or f"row {i + 1}", layer_name=layer_name, look=row["look"], color=_look_color(row),
                              in_range=row["in_range"], on=layer is not None, row=row)
        infos.append(info)
        if layer is None:
            continue
        ls = views[i] = layer_view(settings, row)
        try:
            wl = None
            if ls.screens and ls.wl_table_id:
                key = (ls.wl_table_id, ls.wl_table_name_field, ls.wl_table_elev_field, ls.wl_table_date_field,
                       ls.wl_table_kind_field, tuple(ls.wl_atd_values))
                wl = wl_cache[key] if key in wl_cache else wl_cache.setdefault(key, read_wl_table(ls, project))
                if getattr(wl, "warning", ""):
                    wl_warnings.setdefault((ls.wl_table_id, ls.wl_table_elev_field), wl.warning)
            row_hits, row_beyond, row_near = find_explorations(line, layer, ls, crs, sampler, dist_factor, project,
                                                               ground=ground, wl_table=wl)
        except SectionError as exc:
            if several:
                raise SectionError(f"{info.name}: {exc}") from None
            raise
        styles: Dict[int, tuple] = {}
        if info.look == "color":                         # plotted and left-off hits alike (Black, Gray: never read)
            try:
                info.style, styles = read_styles(layer, [h.fid for h in row_hits], project)
            except Exception as exc:         # a renderer that can't be read: this row in black, never a failed section
                QgsMessageLog.logMessage(traceback.format_exc(), "XSections", Qgis.MessageLevel.Warning)
                info.style, styles = None, {}
                warnings.append(f"{info.name}: its style in QGIS could not be read ({type(exc).__name__}); its lines "
                                "are drawn in black.")
        for h in row_hits:
            h.layer_index, h.layer_id, h.layer_name = i, row["layer_id"], info.name
            h.look, h.color, h.in_range = info.look, info.color, info.in_range
            if info.look == "color":
                h.style_rank, h.color = styles.get(h.fid, (-1, ""))
            if hidden_key(lk, row["layer_id"], h.fid) in hidden:
                left_off.append(h)
                info.left_off += 1
            else:
                hits.append(h)
                info.plotted += 1
        info.near, info.beyond = row_near, list(row_beyond)
        near_count += row_near
        beyond += [f"{b} ({info.name})" for b in row_beyond] if len(layers) > 1 else row_beyond
    order = lambda h: (h.station, h.layer_index, h.label)    # noqa: E731 (one row: by (station, label), as before)
    hits.sort(key=order)
    left_off.sort(key=order)

    # --- other points, row by row (a missing elevation field is an error naming the row)
    other_infos: List[OtherLayerInfo] = []
    other_points: List[OtherPoint] = []
    for j, d in enumerate(others):
        layer = other_layers.get(j)
        layer_name = layer.name() if layer is not None else _layer_name(project, d["layer_id"])
        oinfo = OtherLayerInfo(index=j, layer_id=d["layer_id"], name=point_legend_name(d, layer_name)
                               or f"row {j + 1}", layer_name=layer_name, shape=d["shape"], color=d["color"],
                               size=d["size"], elev=d["elev"], elev_field=d["elev_field"],
                               elev_empty=d["elev_empty"], on=layer is not None, row=d)
        other_infos.append(oinfo)
        if layer is None:
            continue
        try:
            pts, o_beyond, o_near, no_elev = find_other_points(line, layer, d, settings, crs, sampler, dist_factor,
                                                               project, ground)
        except SectionError as exc:
            raise SectionError(f"{oinfo.name}: {exc}") from None
        for p in pts:
            p.layer_index, p.layer_id, p.layer_name = j, d["layer_id"], oinfo.name
        oinfo.plotted, oinfo.near, oinfo.beyond, oinfo.no_elevation = len(pts), o_near, o_beyond, no_elev
        other_points += pts
    other_points.sort(key=lambda p: (p.station, p.layer_index, p.label))

    if not layers and not other_layers:
        warnings.append(NO_POINTS)
    if z_how == "assumed":
        warnings.append(f"The DEM does not state its elevation units; assumed {_Z_NAMES[z_units]} "
                        "(its map units). Set them under Surfaces > More: units and datum if that is wrong.")
    if ground.gaps:
        pct = 100.0 * (1.0 - ground.coverage)
        warnings.append(f"No DEM data along {pct:.1f}% of the line ({_plural(len(ground.gaps), 'gap')}).")
    if step > cell * 1.0001 and math.isfinite(cell):
        warnings.append(f"Ground sampled every {step:.1f} ft (coarser than the {cell:.2f} ft DEM cells) "
                        "because the line is very long.")
    warnings += gone
    warnings += list(wl_warnings.values())
    if layers and not hits and not left_off:
        text = f"No explorations within {settings.tolerance_ft:g} ft of the line."
        if not beyond and not near_count:
            nearest = min(nearest_distance_ft(line, layers[i], views[i], crs, dist_factor, project) for i in layers)
            if math.isfinite(nearest) and nearest > max(FAR_FT, 10.0 * settings.tolerance_ft):
                text += (f" The nearest is {nearest / FAR_FT:,.1f} mi away: if they should be near, check "
                         "the point layer's CRS (Layer Properties > Source).")
        warnings.append(text)
    elif left_off and not hits:
        warnings.append(f"Every exploration within {settings.tolerance_ft:g} ft of the line is left off "
                        "(see Plotted explorations).")
    if beyond:
        warnings.append(f"Left out past the ends of the line: {', '.join(beyond)}.")
    for h in hits:
        for flag in h.flags:
            warnings.append(f"{h.label}: {flag}")
    for p in other_points:
        for flag in p.flags:
            warnings.append(f"{p.label}: {flag}")

    verts = line_vertices(line)
    (x0, y0), (x1, y1) = verts[0], verts[-1]
    first_on = next((info for info in infos if info.on), None)
    return SectionModel(
        length=length,
        vertex_stations=vstations,
        azimuth=azimuth_deg(float(x1 - x0), float(y1 - y0)),
        ground=ground,
        hits=hits,
        beyond_ends=beyond,
        near_count=near_count,
        warnings=warnings,
        section_crs_wkt=crs.toWkt(),
        line_wkt=line.asWkt(),
        dem_name=dem.name(),
        points_name=first_on.layer_name if first_on is not None else "",
        dist_factor=dist_factor,
        has_explorations=bool(layers),
        surfaces=surfaces,
        point_layers=infos,
        left_off=left_off,
        other_points=other_points,
        other_layers=other_infos,
        line_key=lk,
    )


def build_surfaces(settings: Settings, project: QgsProject, line, crs, dist_factor: float, length: float,
                   warnings: List[str]) -> List[SurfaceProfile]:
    """The other surfaces (settings.surfaces, visible ones, in order) sampled along the line: rasters, and
    MODFLOW 6 model surfaces (source "mf6", core/mf6_section.py). A surface that can't be drawn (layer or model
    file gone, no such band or layer, off the line) is left out with a warning: it never stops the section."""
    out: List[SurfaceProfile] = []
    ctx = project.transformContext()
    begin_build()
    for i, d in enumerate(clean_surfaces(settings.surfaces), 1):
        if not d["visible"]:
            continue
        if d["source"] == "mf6":
            try:
                sp = model_surface(d, project, line, crs, dist_factor, length, warnings)
            except Exception as exc:          # an unexpected file state or a reader bug: this surface only
                QgsMessageLog.logMessage(traceback.format_exc(), "XSections", Qgis.MessageLevel.Warning)
                label = d["name"].strip() or surface_name(d["mf6_var"], int(d["mf6_layer"]))
                warnings.append(f"Surface “{label}”: unexpected error ({type(exc).__name__}: {exc}); left out. "
                                "Details are in the XSections log.")
                continue
            if sp is not None:
                out.append(sp)
            continue
        layer = project.mapLayer(d["layer_id"]) if d["layer_id"] else None
        label = d["name"].strip() or (layer.name() if isinstance(layer, QgsRasterLayer) else f"Surface {i}")
        if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
            warnings.append(f"Surface “{label}”: its raster is no longer in the project; left out.")
            continue
        band = int(d["band"])
        if band < 1 or band > layer.bandCount():
            warnings.append(f"Surface “{label}”: {layer.name()} has no band {band}; left out.")
            continue
        if not d["name"].strip() and layer.bandCount() > 1:
            label = f"{layer.name()} band {band}"
        z_units, z_factor, z_how = resolve_z_units(layer, d["z_units"], band)
        try:
            samp = raster_sampler(layer, band, crs, z_factor, ctx)
        except SectionError as exc:
            warnings.append(f"Surface “{label}”: {exc} Left out.")
            continue
        cell = dem_cell_size_ft(layer, crs, dist_factor, ctx)
        step = cell if math.isfinite(cell) and cell > 0 else length / 1000.0
        step = max(step, length / MAX_SAMPLES)
        stations, z, coverage = surface_profile(line, samp, d["mode"], step, dist_factor, cell)
        if coverage <= 0.0:
            warnings.append(f"Surface “{label}” ({layer.name()}) has no data along the line; left out.")
            continue
        if z_how == "assumed":
            warnings.append(f"Surface “{label}”: {layer.name()} does not state its elevation units; assumed "
                            f"{_Z_NAMES[z_units]}. Set them in the surface's settings if that is wrong.")
        out.append(SurfaceProfile(name=label, color=d["color"], style=d["style"], width=float(d["width"]),
                                  mode=d["mode"], stations=list(stations), z=list(z), in_range=bool(d["in_range"]),
                                  marks=bool(d["marks"]), layer_name=layer.name(), band=band, coverage=coverage,
                                  step=float(cell if d["mode"] == "cells" else step)))
    return out
