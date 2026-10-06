"""Synthetic test data in EPSG:2927 (WA State Plane South, US survey feet) with known answers.

Import `start_app()` first in every test module; it creates one headless QgsApplication.
"""
import atexit
import math
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Every temp file a test run makes (DEMs, exports, the QGIS profile) goes under one folder that is
# removed when the run ends (files QGIS still holds open are skipped).
RUN_TMP = tempfile.mkdtemp(prefix="xsec_run_")
tempfile.tempdir = RUN_TMP
atexit.register(shutil.rmtree, RUN_TMP, True)

_APP = None


def start_app():
    """One QgsApplication (GUI-capable, offscreen) for the whole test run.

    User settings (e.g. the plugin's last export folder) go to a throwaway profile folder, so tests
    never write into a real QGIS profile.
    """
    global _APP
    from qgis.core import QgsApplication
    if QgsApplication.instance() is None:
        # (QgsApplication's profileFolder argument does not move QgsSettings; this variable does)
        os.environ["QGIS_CUSTOM_CONFIG_PATH"] = tempfile.mkdtemp(prefix="xsec_profile_")
        _APP = QgsApplication([], True)
        _APP.initQgis()
    return QgsApplication.instance()


CRS = "EPSG:2927"
X0, Y0 = 1_200_000.0, 650_000.0          # lower-left of the DEM, ftUS
NX, NY, CELL = 2000, 1400, 3.0            # 6,000 x 4,200 ft at 3 ft
# nodata disc (cx, cy, r) centred on the section line at station ~3990 (B-3's station), so the
# ground profile has one gap at stations ~3930-4050. (Was (X0+3900, Y0+2200): 67 ft off the line, no gap.)
HOLE = (X0 + 4427.0, Y0 + 2428.0, 60.0)

# section line: 3 vertices, one bend (map coordinates)
LINE = [(X0 + 500.0, Y0 + 2000.0), (X0 + 3000.0, Y0 + 2000.0), (X0 + 5000.0, Y0 + 2600.0)]


def plane_z(x, y):
    """Exact under bilinear interpolation."""
    return 500.0 + 0.01 * (x - X0) + 0.005 * (y - Y0)


def terrain_z(x, y):
    d = x - (X0 + 3000.0)
    return plane_z(x, y) - 40.0 * math.exp(-(d * d) / (2 * 600.0 ** 2))


def make_dem(path=None, kind="plane", hole=True):
    """GeoTIFF DEM in feet; returns the path. kind: plane | terrain."""
    import numpy as np
    from osgeo import gdal, osr
    gdal.UseExceptions()
    path = path or os.path.join(tempfile.mkdtemp(prefix="xsec_"), f"dem_{kind}.tif")
    xs = X0 + (np.arange(NX) + 0.5) * CELL
    ys = Y0 + NY * CELL - (np.arange(NY) + 0.5) * CELL
    X, Y = np.meshgrid(xs, ys)
    Z = 500.0 + 0.01 * (X - X0) + 0.005 * (Y - Y0)
    if kind == "terrain":
        Z = Z - 40.0 * np.exp(-((X - (X0 + 3000.0)) ** 2) / (2 * 600.0 ** 2))
    nod = -9999.0
    if hole:
        cx, cy, r = HOLE
        Z[(X - cx) ** 2 + (Y - cy) ** 2 < r * r] = nod
    ds = gdal.GetDriverByName("GTiff").Create(path, NX, NY, 1, gdal.GDT_Float32, ["COMPRESS=DEFLATE", "TILED=YES"])
    ds.SetGeoTransform((X0, CELL, 0, Y0 + NY * CELL, 0, -CELL))
    srs = osr.SpatialReference(); srs.ImportFromEPSG(2927)
    ds.SetProjection(srs.ExportToWkt())
    b = ds.GetRasterBand(1); b.SetNoDataValue(nod); b.WriteArray(Z.astype("float32")); b.SetUnitType("ft")
    ds.FlushCache(); ds = None
    return path


def line_length():
    return sum(math.dist(LINE[i], LINE[i + 1]) for i in range(len(LINE) - 1))


def point_at(station, offset_left=0.0):
    """Map x, y at `station` along LINE, offset to the LEFT (positive) or right (negative)."""
    acc = 0.0
    for (x1, y1), (x2, y2) in zip(LINE, LINE[1:]):
        L = math.dist((x1, y1), (x2, y2))
        if station <= acc + L or (x2, y2) == LINE[-1]:
            t = (station - acc) / L
            ux, uy = (x2 - x1) / L, (y2 - y1) / L
            return x1 + ux * t * L - uy * offset_left, y1 + uy * t * L + ux * offset_left
        acc += L


# (name, type, station, offset_left, depth, top_field)
#   top_field: None = null, 0 = "missing" zero, "dem" = DEM at the point, number = that elevation
EXPLORATIONS = [
    ("B-1", "Boring", 300.0, 40.0, 30.0, "dem"),
    ("MW-1", "Monitoring Well", 900.0, -60.0, 25.0, None),       # no top -> LIDAR at point
    ("TP-1", "Test Pit", 1500.0, 20.0, 10.0, 0),                 # zero -> LIDAR at point
    ("B-2", "Boring", 2200.0, -120.0, 45.0, "dem+6"),             # collar 6 ft above LIDAR -> tick raised
    ("MW-2", "Monitoring Well", 2900.0, 90.0, 35.0, 205.6),      # wrong top (> 25 ft off) -> LIDAR + flag
    ("CPT-1", "CPT", 3700.0, -30.0, 60.0, "dem"),
    ("B-3", "Boring", 3990.0, 10.0, None, None),                 # station inside the nodata hole, no depth
    ("B-far", "Boring", 1200.0, 400.0, 30.0, "dem"),             # beyond tolerance (150)
    ("B-pre", "Boring", -80.0, 10.0, 30.0, "dem"),               # past the start: left out
    ("B-post", "Boring", None, None, 30.0, "dem"),               # past the end: placed below
]
TOLERANCE = 150.0

# BotElev variant (make_points_layer(bot_elev=True)): a bottom-elevation field next to ExploDepth.
#   ("top", d) = the stored ExploElev + d; ("lidar", d) = LIDAR at the point + d; a number = that value;
#   missing = NULL. Each row exercises one rule of the bottom precedence (DESIGN.md decision 2).
BOT_ELEV = {
    "B-1": ("top", -30.0),      # table top, table bottom agrees with top - depth: bottom from BotElev
    "TP-1": ("lidar", -18.0),   # top 0 -> LIDAR; BotElev 8 ft off top - depth: BotElev kept, info flag
    "B-2": ("top", 5.0),        # BotElev above the top: rejected, falls back to top - depth, flag
    "MW-2": ("lidar", -35.0),   # wrong table top -> LIDAR; BotElev below it: bottom from BotElev
    "CPT-1": 0.0,               # 0 = missing: top - depth
    "B-3": 450.0,               # no top at all (in the DEM hole): no line whatever the bottom
}                               # MW-1: NULL BotElev, no table top: LIDAR - depth


def _explo_xy(station, off):
    if station is None:                                          # 80 ft past the end along the last segment
        (x1, y1), (x2, y2) = LINE[-2], LINE[-1]
        L = math.dist((x1, y1), (x2, y2)); ux, uy = (x2 - x1) / L, (y2 - y1) / L
        return x2 + ux * 80.0, y2 + uy * 80.0
    if station < 0:
        (x1, y1), (x2, y2) = LINE[0], LINE[1]
        L = math.dist((x1, y1), (x2, y2)); ux, uy = (x2 - x1) / L, (y2 - y1) / L
        return x1 + ux * station - uy * off, y1 + uy * station + ux * off
    return point_at(station, off)


def make_points_layer(crs=CRS, kind="plane", name="Explorations", bot_elev=False):
    """Memory point layer with ExploName, ExploType, ExploDepth, ExploElev (and BotElev from BOT_ELEV when
    `bot_elev`). Coordinates in `crs`."""
    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsField,
                           QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer)
    from qgis.PyQt.QtCore import QMetaType
    zf = terrain_z if kind == "terrain" else plane_z
    lyr = QgsVectorLayer(f"Point?crs={crs}", name, "memory")
    pr = lyr.dataProvider()
    pr.addAttributes([QgsField("ExploName", QMetaType.Type.QString), QgsField("ExploType", QMetaType.Type.QString),
                      QgsField("ExploDepth", QMetaType.Type.Double), QgsField("ExploElev", QMetaType.Type.Double)]
                     + ([QgsField("BotElev", QMetaType.Type.Double)] if bot_elev else []))
    lyr.updateFields()
    ct = QgsCoordinateTransform(QgsCoordinateReferenceSystem(CRS), QgsCoordinateReferenceSystem(crs), QgsProject.instance())
    feats = []
    for name_, typ, st, off, depth, top in EXPLORATIONS:
        x, y = _explo_xy(st, off)
        if top == "dem":
            topv = round(zf(x, y), 2)
        elif top == "dem+6":
            topv = round(zf(x, y) + 6.0, 2)
        else:
            topv = top
        f = QgsFeature(lyr.fields())
        attrs = [name_, typ, depth, topv]
        if bot_elev:
            spec = BOT_ELEV.get(name_)
            if isinstance(spec, tuple):
                base = topv if spec[0] == "top" else zf(x, y)
                spec = round(base + spec[1], 2)
            attrs.append(spec)
        f.setAttributes(attrs)
        g = QgsGeometry.fromPointXY(QgsPointXY(x, y))
        if crs != CRS:
            g.transform(ct)
        f.setGeometry(g)
        feats.append(f)
    pr.addFeatures(feats)
    lyr.updateExtents()
    return lyr


def make_line_layer(crs=CRS, name="Section_Lines"):
    """Memory LineString layer with one feature (fid 1): the bent LINE, field `name` = "A"."""
    from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsVectorLayer
    from qgis.PyQt.QtCore import QMetaType
    lyr = QgsVectorLayer(f"LineString?crs={crs}", name, "memory")
    lyr.dataProvider().addAttributes([QgsField("name", QMetaType.Type.QString)])
    lyr.updateFields()
    f = QgsFeature(lyr.fields()); f.setAttributes(["A"])
    f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in LINE]))
    lyr.dataProvider().addFeatures([f]); lyr.updateExtents()
    return lyr


def load_project(kind="plane", hole=True, points_crs=CRS, bot_elev=False):
    """Fresh QgsProject.instance() with DEM, points and line layers. Returns (project, dem, pts, lines)."""
    from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsRasterLayer
    start_app()
    prj = QgsProject.instance(); prj.clear()
    prj.setCrs(QgsCoordinateReferenceSystem(CRS))
    dem = QgsRasterLayer(make_dem(kind=kind, hole=hole), "LIDAR_DEM_3ft")
    pts = make_points_layer(crs=points_crs, kind=kind, bot_elev=bot_elev)
    lines = make_line_layer()
    prj.addMapLayers([dem, pts, lines])
    return prj, dem, pts, lines


# The standard sheet layout: the defaults up to 0.1.1 (settings version 3). Since 0.1.2 the defaults are the
# compact layout with the grid filled below the section; tests of the standard geometry (margins, page
# placement, elevation limits, notes text) pin this instead.
STANDARD_LAYOUT = dict(compact_layout=False, fill_grid="off")


def default_settings(prj, dem, pts, lines, **over):
    from xsections.core.model import Settings
    s = Settings(line_layer_id=lines.id(), line_fid=next(lines.getFeatures()).id(),
                 dem_layer_id=dem.id(), points_layer_id=pts.id(), label_field="ExploName",
                 type_field="ExploType", tolerance_ft=TOLERANCE, top_field="ExploElev",
                 depth_field="ExploDepth")
    for k, v in over.items():
        setattr(s, k, v)
    return s


REALDATA = os.environ.get("XSECTIONS_REALDATA", "")
