import os
import tempfile
import unittest

from tests.fixtures import REALDATA, make_dem, start_app

start_app()

from qgis.core import QgsCoordinateReferenceSystem, QgsRasterLayer  # noqa: E402

from xsections.core.model import SectionError  # noqa: E402
from xsections.core.units import (detect_z_units, distance_factor_to_ft, parse_unit_text,  # noqa: E402
                                  resolve_z_units, z_factor_to_ft)

FTUS = 1200.0 / 3937.0 / 0.3048      # 1.000002


def make_tiny_dem(epsg=2927, unit="", origin=(1_200_000.0, 650_000.0), cell=3.0, n=10, value=100.0,
                  path=None):
    """Small constant GeoTIFF with an optional band unit type. Returns the path."""
    import numpy as np
    from osgeo import gdal, osr
    gdal.UseExceptions()
    path = path or os.path.join(tempfile.mkdtemp(prefix="xsec_units_"), "tiny.tif")
    ds = gdal.GetDriverByName("GTiff").Create(path, n, n, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((origin[0], cell, 0, origin[1] + n * cell, 0, -cell))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    b = ds.GetRasterBand(1)
    b.WriteArray(np.full((n, n), value, dtype="float32"))
    if unit:
        b.SetUnitType(unit)
    ds.FlushCache()
    ds = None
    return path


class DistanceFactor(unittest.TestCase):
    def test_us_survey_feet(self):
        for code in ("EPSG:2927", "EPSG:2926"):
            f = distance_factor_to_ft(QgsCoordinateReferenceSystem(code))
            self.assertAlmostEqual(f, FTUS, delta=1e-9, msg=code)
            self.assertAlmostEqual(f, 1.000002, delta=1e-7)

    def test_metres(self):
        self.assertAlmostEqual(distance_factor_to_ft(QgsCoordinateReferenceSystem("EPSG:32610")), 3.28084, delta=1e-5)

    def test_geographic_raises(self):
        with self.assertRaises(SectionError) as cm:
            distance_factor_to_ft(QgsCoordinateReferenceSystem("EPSG:4326"))
        self.assertIn("geographic", str(cm.exception))

    def test_invalid_raises(self):
        with self.assertRaises(SectionError):
            distance_factor_to_ft(QgsCoordinateReferenceSystem())


class ZUnits(unittest.TestCase):
    def test_parse_unit_text(self):
        cases = {"ft": "ft", "foot": "ft", "Feet": "ft", "US survey foot": "ftUS", "US_survey_foot": "ftUS",
                 "ftUS": "ftUS", "us-ft": "ftUS", "m": "m", "metre": "m", "Meters": "m", "": "unknown",
                 "kilometre": "unknown", "degree": "unknown"}
        for text, want in cases.items():
            self.assertEqual(parse_unit_text(text), want, text)

    def _layer(self, **kw):
        lyr = QgsRasterLayer(make_tiny_dem(**kw), "tiny")
        self.assertTrue(lyr.isValid())
        return lyr

    def test_band_unit_detected(self):
        self.assertEqual(detect_z_units(QgsRasterLayer(make_dem(hole=False), "dem")), "ft")
        for unit, want in (("ft", "ft"), ("foot", "ft"), ("US survey foot", "ftUS"), ("metre", "m"), ("m", "m")):
            self.assertEqual(detect_z_units(self._layer(unit=unit)), want, unit)

    def test_no_unit_is_unknown(self):
        self.assertEqual(detect_z_units(self._layer()), "unknown")

    def test_factors(self):
        ft = self._layer(unit="ft")
        self.assertEqual(z_factor_to_ft(ft, "auto"), 1.0)
        self.assertAlmostEqual(z_factor_to_ft(ft, "m"), 3.28084, delta=1e-5)      # explicit setting wins
        self.assertAlmostEqual(z_factor_to_ft(ft, "ftUS"), FTUS, delta=1e-9)
        self.assertEqual(z_factor_to_ft(ft, "ft"), 1.0)
        self.assertAlmostEqual(z_factor_to_ft(self._layer(unit="metre"), "auto"), 3.28084, delta=1e-5)

    def test_unknown_uses_crs_units(self):
        units, f, how = resolve_z_units(self._layer(epsg=2927), "auto")
        self.assertEqual((units, how), ("ftUS", "assumed"))
        self.assertAlmostEqual(f, 1.0, delta=1e-5)
        self.assertAlmostEqual(z_factor_to_ft(self._layer(epsg=32610, origin=(500_000.0, 5_200_000.0)), "auto"),
                               3.28084, delta=1e-5)
        # geographic DEM, no unit: metres (SRTM / 3DEP convention)
        geo = self._layer(epsg=4326, origin=(-122.3, 47.1), cell=0.0001)
        self.assertAlmostEqual(z_factor_to_ft(geo, "auto"), 3.28084, delta=1e-5)

    def test_vertical_crs(self):
        lyr = self._layer()
        ok, _msg = lyr.setVerticalCrs(QgsCoordinateReferenceSystem("EPSG:5703"))   # NAVD88 height (m)
        if not ok:
            self.skipTest("layer does not accept a vertical CRS")
        self.assertEqual(detect_z_units(lyr), "m")
        ok, _msg = lyr.setVerticalCrs(QgsCoordinateReferenceSystem("EPSG:6360"))   # NAVD88 height (ftUS)
        if ok:
            self.assertEqual(detect_z_units(lyr), "ftUS")


@unittest.skipUnless(REALDATA, "set XSECTIONS_REALDATA to the copied real-data folder")
class RealDataUnits(unittest.TestCase):
    def test_cdf_lidar_is_feet(self):
        lyr = QgsRasterLayer(os.path.join(REALDATA, "cdf_lidar.tif"), "cdf_lidar")
        self.assertTrue(lyr.isValid())
        self.assertEqual(detect_z_units(lyr), "unknown")          # no band unit, no vertical CRS
        self.assertAlmostEqual(z_factor_to_ft(lyr, "auto"), 1.0, delta=1e-5)
        self.assertAlmostEqual(distance_factor_to_ft(lyr.crs()), 1.000002, delta=1e-7)


if __name__ == "__main__":
    unittest.main()
