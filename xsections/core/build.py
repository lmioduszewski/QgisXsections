"""build_section: settings + project -> SectionModel (geometry and data only, no drawing)."""
from __future__ import annotations

import math
import traceback
from typing import List, Optional

from qgis.core import Qgis, QgsMessageLog, QgsProject, QgsRasterLayer, QgsVectorLayer

from .explorations import find_explorations, nearest_distance_ft, read_wl_table
from .mf6_section import begin_build, model_surface, surface_name
from .model import NO_POINTS, SectionError, SectionModel, Settings, SurfaceProfile, clean_surfaces
from .section import (azimuth_deg, dem_cell_size_ft, ground_profile, line_vertices, raster_sampler,
                      resolve_line, section_crs, surface_profile, vertex_stations)
from .units import distance_factor_to_ft, resolve_z_units

MAX_SAMPLES = 200_000          # ground samples per line; the step grows past this (very long lines)
FAR_FT = 5280.0                # nothing within a mile of the line: hint at a wrong point layer CRS
_Z_NAMES = {"ft": "feet", "ftUS": "US survey feet", "m": "meters"}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def build_section(settings: Settings, project: Optional[QgsProject] = None) -> SectionModel:
    """Resolve layers by id, sample the ground, project the explorations. Raises SectionError with a
    message fit for the panel when something the user can fix is missing or wrong."""
    project = project or QgsProject.instance()

    dem = project.mapLayer(settings.dem_layer_id) if settings.dem_layer_id else None
    if not isinstance(dem, QgsRasterLayer):
        raise SectionError("Choose a DEM (ground surface raster).")
    if not dem.isValid():
        raise SectionError(f"The DEM {dem.name()} could not be read.")
    band = int(settings.dem_band or 1)
    if band < 1 or band > dem.bandCount():
        raise SectionError(f"The DEM {dem.name()} has no band {band}.")

    # the explorations layer is optional: without one the sheet shows the ground line only
    pts = project.mapLayer(settings.points_layer_id) if settings.points_layer_id else None
    if settings.points_layer_id and not isinstance(pts, QgsVectorLayer):
        raise SectionError("The explorations (points) layer is no longer in the project. Choose another, "
                           "or none for a ground line only.")
    if pts is not None and not pts.isValid():
        raise SectionError(f"The explorations layer {pts.name()} could not be read.")

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

    if pts is not None:
        wl_rows = read_wl_table(settings, project) if settings.screens and settings.wl_table_id else None
        hits, beyond, near_count = find_explorations(line, pts, settings, crs, sampler, dist_factor, project,
                                                     ground=ground, wl_table=wl_rows)
    else:
        hits, beyond, near_count = [], [], 0

    if pts is None:
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
    if pts is not None and not hits:
        text = f"No explorations within {settings.tolerance_ft:g} ft of the line."
        if not beyond and not near_count:
            nearest = nearest_distance_ft(line, pts, settings, crs, dist_factor, project)
            if math.isfinite(nearest) and nearest > max(FAR_FT, 10.0 * settings.tolerance_ft):
                text += (f" The nearest is {nearest / FAR_FT:,.1f} mi away: if they should be near, check "
                         "the point layer's CRS (Layer Properties > Source).")
        warnings.append(text)
    if beyond:
        warnings.append(f"Left out past the ends of the line: {', '.join(beyond)}.")
    for h in hits:
        for flag in h.flags:
            warnings.append(f"{h.label}: {flag}")

    verts = line_vertices(line)
    (x0, y0), (x1, y1) = verts[0], verts[-1]
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
        points_name=pts.name() if pts is not None else "",
        dist_factor=dist_factor,
        has_explorations=pts is not None,
        surfaces=surfaces,
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
