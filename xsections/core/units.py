"""Unit handling: CRS distance units and DEM elevation (z) units, both converted to feet.

US survey feet are treated as feet through QGIS's own factor (2 ppm, negligible; decision 5).
"""
from __future__ import annotations

import re
from typing import Tuple

from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsRasterLayer, QgsUnitTypes)

from .model import SectionError

FT = Qgis.DistanceUnit.Feet

# z-unit code -> QGIS distance unit
_Z_UNITS = {
    "ft": Qgis.DistanceUnit.Feet,
    "ftUS": Qgis.DistanceUnit.FeetUSSurvey,
    "m": Qgis.DistanceUnit.Meters,
}

# normalised unit text (lower case, letters only) -> z-unit code
_UNIT_WORDS = {
    "ft": "ft", "foot": "ft", "feet": "ft", "intlfoot": "ft", "internationalfoot": "ft",
    "internationalfeet": "ft",
    "usft": "ftUS", "ftus": "ftUS", "ussurveyfoot": "ftUS", "ussurveyfeet": "ftUS",
    "surveyfoot": "ftUS", "surveyfeet": "ftUS", "usfoot": "ftUS", "usfeet": "ftUS",
    "m": "m", "meter": "m", "meters": "m", "metre": "m", "metres": "m", "metro": "m",
}


def _unit_factor(unit: Qgis.DistanceUnit) -> float:
    return QgsUnitTypes.fromUnitToUnitFactor(unit, FT)


def distance_factor_to_ft(crs: QgsCoordinateReferenceSystem) -> float:
    """Feet per CRS map unit. Raises SectionError for a missing or geographic CRS."""
    if crs is None or not crs.isValid():
        raise SectionError("The section needs a coordinate reference system; the layer has none.")
    if crs.isGeographic():
        raise SectionError(
            f"{crs.description() or crs.authid()} is geographic (degrees). Use a projected CRS in "
            "feet or meters, e.g. EPSG:2927 (WA South, ftUS).")
    unit = crs.mapUnits()
    if unit in (Qgis.DistanceUnit.Unknown, Qgis.DistanceUnit.Degrees):
        raise SectionError(f"The distance units of {crs.description() or crs.authid()} are unknown.")
    factor = _unit_factor(unit)
    if not factor or factor != factor:          # 0 or nan
        raise SectionError(f"Cannot convert the units of {crs.description() or crs.authid()} to feet.")
    return factor


def parse_unit_text(text: str) -> str:
    """'US survey foot' -> 'ftUS', 'metre' -> 'm', 'ft' -> 'ft'; anything else -> 'unknown'."""
    key = re.sub(r"[^a-z]", "", (text or "").lower())
    return _UNIT_WORDS.get(key, "unknown")


def _unit_code(unit: Qgis.DistanceUnit) -> str:
    for code, u in _Z_UNITS.items():
        if unit == u:
            return code
    return "unknown"


def _gdal_band_unit(layer: QgsRasterLayer, band: int) -> str:
    """GDAL band unit type ('' when the provider is not GDAL or the file cannot be opened)."""
    if layer.providerType() != "gdal":
        return ""
    try:
        from osgeo import gdal
    except ImportError:
        return ""
    src = layer.source().split("|")[0]
    try:
        if hasattr(gdal, "ExceptionMgr"):
            with gdal.ExceptionMgr(useExceptions=True):
                ds = gdal.Open(src, gdal.GA_ReadOnly)
        else:
            ds = gdal.Open(src, gdal.GA_ReadOnly)
        if ds is None or band < 1 or band > ds.RasterCount:
            return ""
        return ds.GetRasterBand(band).GetUnitType() or ""
    except Exception:  # noqa: BLE001 - any GDAL failure just means "no unit"
        return ""


def detect_z_units(layer: QgsRasterLayer, band: int = 1) -> str:
    """'ft' | 'ftUS' | 'm' | 'unknown', from the GDAL band unit, else the layer's vertical CRS."""
    code = parse_unit_text(_gdal_band_unit(layer, band))
    if code != "unknown":
        return code
    for vcrs in (layer.verticalCrs(), layer.crs().verticalCrs()):
        if vcrs is not None and vcrs.isValid():
            code = _unit_code(vcrs.mapUnits())
            if code != "unknown":
                return code
    return "unknown"


def resolve_z_units(layer: QgsRasterLayer, setting: str, band: int = 1) -> Tuple[str, float, str]:
    """(units, feet per DEM z unit, how it was decided). `how` is 'set', 'detected' or 'assumed'."""
    if setting in _Z_UNITS:
        return setting, _unit_factor(_Z_UNITS[setting]), "set"
    code = detect_z_units(layer, band)
    if code != "unknown":
        return code, _unit_factor(_Z_UNITS[code]), "detected"
    # Unknown: same as the horizontal units (LIDAR in State Plane feet is in feet). Geographic
    # DEMs (SRTM, 3DEP) are metres.
    crs = layer.crs()
    code = "m"
    if crs.isValid() and not crs.isGeographic():
        code = _unit_code(crs.mapUnits())
        if code == "unknown":
            code = "m"
    return code, _unit_factor(_Z_UNITS[code]), "assumed"


def z_factor_to_ft(layer: QgsRasterLayer, setting: str, band: int = 1) -> float:
    """Feet per DEM z unit. setting: auto | ft | ftUS | m; auto with unknown units uses the CRS units."""
    return resolve_z_units(layer, setting, band)[1]
