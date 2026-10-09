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
# removed when the run ends (files QGIS still holds open are skipped). scripts/run_tests_parallel.py gives its
# processes a tag (XSECTIONS_RUN_TAG) and removes their folders once they have ended.
RUN_TMP = tempfile.mkdtemp(prefix=f"xsec_run_{os.environ.get('XSECTIONS_RUN_TAG', '')}")
tempfile.tempdir = RUN_TMP
atexit.register(shutil.rmtree, RUN_TMP, True)


# Timing tests (time limits, waits for a timer) multiply their limits and waits by TIME_FACTOR: 1 unless
# XSECTIONS_TIME_FACTOR is set, so a serial run checks exactly as written. scripts/run_tests_parallel.py sets it (3)
# for its workers: several QGIS processes then share the CPUs.
def _time_factor():
    text = os.environ.get("XSECTIONS_TIME_FACTOR", "").strip()
    if not text:
        return 1.0
    try:
        factor = float(text)
    except ValueError:
        factor = float("nan")
    if not factor > 0:
        raise ValueError(f"XSECTIONS_TIME_FACTOR must be a number above 0, not {text!r}")
    return factor


TIME_FACTOR = _time_factor()


def budget(limit):
    """A time limit (seconds or milliseconds alike) times TIME_FACTOR."""
    return limit * TIME_FACTOR


def wait_ms(ms):
    """A wait of `ms` milliseconds times TIME_FACTOR, in whole milliseconds (for QTimer)."""
    return int(round(ms * TIME_FACTOR))


def timing_test(obj):
    """Tag a test method or a test class as a timing test (its limits or waits go through budget / wait_ms). When it
    fails in a parallel run, scripts/run_tests_parallel.py runs it again alone, and that result decides (for any
    other test a parallel failure stays a failure). The launcher finds the tag by reading the source (ast), so write
    it as `@timing_test`. It changes nothing when the test runs."""
    obj.xsections_timing_test = True
    return obj


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


# ---------------------------------------------------------------------------------------- 0.3.3: point layers
# His GeoPackage (read only, always: tests byte-copy it and open the copy). Tests are not shipped.
GPKG = os.environ.get("XSECTIONS_GPKG", r"C:\Users\lukem\QGIS\SHP\Explorations.gpkg")


def _memory_points(name, fields, rows, crs=CRS):
    """Memory point layer `name`: `fields` [(field name, QMetaType.Type)], `rows` [(x, y, [attributes])] in CRS
    (EPSG:2927), transformed to `crs`."""
    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsField, QgsGeometry,
                           QgsPointXY, QgsProject, QgsVectorLayer)
    lyr = QgsVectorLayer(f"Point?crs={crs}", name, "memory")
    lyr.dataProvider().addAttributes([QgsField(n, t) for n, t in fields])
    lyr.updateFields()
    ct = QgsCoordinateTransform(QgsCoordinateReferenceSystem(CRS), QgsCoordinateReferenceSystem(crs),
                                QgsProject.instance())
    feats = []
    for x, y, attrs in rows:
        f = QgsFeature(lyr.fields())
        f.setAttributes(list(attrs))
        g = QgsGeometry.fromPointXY(QgsPointXY(x, y))
        if crs != CRS:
            g.transform(ct)
        f.setGeometry(g)
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    lyr.updateExtents()
    return lyr


# Explorations by others: (name, ExploType_resolved, ExploType, station, offset_left, depth, top)
#   top: "dem" = DEM at the point (rounded), None = NULL
OTHERS = [
    ("B-2x", "Boring", "B", 2200.0, -119.4, 40.0, "dem"),            # 0.6 ft from B-2: both plotted
    ("O-1", "Boring", "B", 600.0, 50.0, 20.0, "dem"),
    ("O-2", None, "?", 1700.0, -40.0, 15.0, None),                    # NULL type
    ("O-3", "", "", 3300.0, 70.0, 25.0, "dem"),                       # empty type
    ("O-4", "Monitoring Well", "MW", 2700.0, 30.0, 30.0, "dem"),
    ("O-far", "Boring", "B", 1200.0, 300.0, 20.0, "dem"),             # beyond the tolerance (within 2.5 x: near)
]


def make_others_layer(crs=CRS, kind="plane", name="Explorations by others"):
    """Explorations by others (OTHERS): ExploName, ExploType_resolved, ExploType (raw codes), ExploDepth,
    ExploElev."""
    from qgis.PyQt.QtCore import QMetaType
    zf = terrain_z if kind == "terrain" else plane_z
    T = QMetaType.Type
    fields = [("ExploName", T.QString), ("ExploType_resolved", T.QString), ("ExploType", T.QString),
              ("ExploDepth", T.Double), ("ExploElev", T.Double)]
    rows = []
    for name_, typ, raw, st, off, depth, top in OTHERS:
        x, y = point_at(st, off)
        rows.append((x, y, [name_, typ, raw, depth, round(zf(x, y), 2) if top == "dem" else None]))
    return _memory_points(name, fields, rows, crs)


# Supply wells: (AESI_MapLabel, ExploType_resolved, WellStatus, station, offset_left, ExploElev, ExploDepth,
#   WellCompleteDepth, GW_Elev_ATD, DepthToGW_ATD, ExploDate in epoch milliseconds)
#   ExploElev "dem" = DEM at the point (rounded); GW_Elev_ATD ("dem", d) = DEM at the point + d
SUPPLY = [
    ("HW-1", "DOMESTIC", "Active", 1800.0, 60.0, "dem", 380.0, 400.0, ("dem", -30.0), 30.0, 1612281600000),
    ("HW-2", None, None, 2600.0, -80.0, None, None, 42.0, 0.0, None, 824745600000),          # GW_Elev_ATD 0
    ("SW-1", "SPRING WELL , GRP A/B/DOM", "Active", 3400.0, 30.0, "dem", 20.0, None, None, None, None),
    ("HW-3", "PUBLIC SUPPLY", None, 1000.0, -100.0, "dem", 150.0, 160.0, ("dem", -60.0), None, -367002000000),
    ("HW-far", "DOMESTIC", "Abandoned", 3000.0, 600.0, None, 100.0, 100.0, None, None, 1733702400000),
]


def make_supply_layer(crs=CRS, kind="plane", name="Supply wells"):
    """Supply wells (SUPPLY): AESI_MapLabel, ExploType_resolved (some NULL), WellStatus, ExploElev, ExploDepth,
    WellCompleteDepth, GW_Elev_ATD (one 0), DepthToGW_ATD, ExploDate (Integer64, epoch milliseconds, as in his
    GeoPackage). HW-1 is 400 ft deep (WellCompleteDepth), HW-2 42 ft."""
    from qgis.PyQt.QtCore import QMetaType
    zf = terrain_z if kind == "terrain" else plane_z
    T = QMetaType.Type
    fields = [("AESI_MapLabel", T.QString), ("ExploType_resolved", T.QString), ("WellStatus", T.QString),
              ("ExploElev", T.Double), ("ExploDepth", T.Double), ("WellCompleteDepth", T.Double),
              ("GW_Elev_ATD", T.Double), ("DepthToGW_ATD", T.Double), ("ExploDate", T.LongLong)]
    rows = []
    for label, typ, status, st, off, elev, depth, complete, gw, dtw, date in SUPPLY:
        x, y = point_at(st, off)
        z = zf(x, y)
        gw_v = round(z + gw[1], 2) if isinstance(gw, tuple) else gw
        rows.append((x, y, [label, typ, status, round(z, 2) if elev == "dem" else None, depth, complete, gw_v, dtw,
                            date]))
    return _memory_points(name, fields, rows, crs)


# Seeps: (Name, Type, station, offset_left, Elev_ft); Elev_ft: None = NULL, "lidar" = the DEM at the point
#   (rounded), ("lidar", d) = DEM + d, a number = that value
SEEPS = [
    ("S-1", "Seep", 1000.0, 20.0, None),                    # no elevation value
    ("S-2", "Seep", 1600.0, -30.0, ("lidar", 1.4)),         # 1.4 ft above the LIDAR at the point
    ("S-3", "Spring", 2400.0, 10.0, 0.0),                   # 0: missing while 0 counts as missing
    ("S-4", "Seep", 2800.0, TOLERANCE + 1.0, "lidar"),      # 1 ft beyond the tolerance: not on the section
    ("S-5", "Seep", 1900.0, -5.0, "lidar"),                 # on the slope of the terrain DEM's valley
]


def make_seeps_layer(crs=CRS, kind="plane", name="Seeps"):
    """Seeps (SEEPS): Name, Type, Elev_ft (ft)."""
    from qgis.PyQt.QtCore import QMetaType
    zf = terrain_z if kind == "terrain" else plane_z
    T = QMetaType.Type
    rows = []
    for name_, typ, st, off, elev in SEEPS:
        x, y = point_at(st, off)
        if elev == "lidar":
            elev = round(zf(x, y), 2)
        elif isinstance(elev, tuple):
            elev = round(zf(x, y) + elev[1], 2)
        rows.append((x, y, [name_, typ, elev]))
    return _memory_points(name, [("Name", T.QString), ("Type", T.QString), ("Elev_ft", T.Double)], rows, crs)


def write_gpkg(layer, name, path=None):
    """`layer` written to a GeoPackage (a new file in RUN_TMP unless `path`) with the layer option FID=id (its fid
    column is "id", as in his Explorations.gpkg; the driver adds the R-tree spatial index), then opened again with
    "ogr". Returns the opened layer, named `name`."""
    from qgis.core import QgsProject, QgsVectorFileWriter, QgsVectorLayer
    path = path or os.path.join(tempfile.mkdtemp(prefix="xsec_gpkg_"), f"{name}.gpkg")
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = name
    opts.layerOptions = ["FID=id"]
    res = QgsVectorFileWriter.writeAsVectorFormatV3(layer, path, QgsProject.instance().transformContext(), opts)
    if res[0] != QgsVectorFileWriter.WriterError.NoError:
        raise RuntimeError(f"writing {path}: {res[1]}")
    out = QgsVectorLayer(f"{path}|layername={name}", name, "ogr")
    if not out.isValid():
        raise RuntimeError(f"{path} could not be opened")
    return out


DENSE_TYPES = ["BORING", "MONITORING WELL", "TEST PIT", "CPT", "EXPLORATION PIT", "HAND AUGER", "PIEZOMETER",
               "WELL", "VIBRACORE", "GEOPROBE", "SONIC", "AIR ROTARY"]
DENSE_NEAR = 60                      # explorations within the tolerance of LINE (labels D-001 ...)


def _dist_to_line(x, y):
    """Distance from each point to LINE (numpy arrays, map units)."""
    import numpy as np
    best = np.full(np.shape(x), np.inf)
    for (x1, y1), (x2, y2) in zip(LINE, LINE[1:]):
        dx, dy = x2 - x1, y2 - y1
        t = np.clip(((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy), 0.0, 1.0)
        best = np.minimum(best, np.hypot(x - (x1 + t * dx), y - (y1 + t * dy)))
    return best


def make_dense_layer(n=32_000, seed=1, name="Explor_dense_pt"):
    """A GeoPackage point layer of `n` explorations (written with write_gpkg, so it has an R-tree, like his
    32,635-point layer): ExploName, ExploType_resolved (DENSE_TYPES, 5 % NULL), ExploDepth, ExploElev (10 % NULL).
    DENSE_NEAR of them lie within 0.9 x TOLERANCE of LINE, between its ends; the rest are spread over a box of 20
    times the area of the line's box, none of them within 400 ft of the line. Made once and cached in the system
    temp folder's xsec_cache, under a name keyed by the generator (its code and data), so that every run reuses one
    file (a copy in each run's RUN_TMP was left behind whenever OGR still held it at exit); each call opens it."""
    import hashlib
    import inspect
    from qgis.core import QgsVectorLayer
    key = hashlib.sha1(repr((n, seed, name, DENSE_NEAR, DENSE_TYPES, LINE, TOLERANCE, CRS) + tuple(
        inspect.getsource(f) for f in (make_dense_layer, write_gpkg, _memory_points, plane_z, point_at, line_length,
                                       _dist_to_line))).encode()).hexdigest()[:10]
    cache = os.path.join(os.path.dirname(RUN_TMP), "xsec_cache")    # the system temp (tempfile.gettempdir() is RUN_TMP)
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, f"dense_{n}_{seed}_{key}.gpkg")
    if not os.path.isfile(path):
        import numpy as np
        from qgis.PyQt.QtCore import QMetaType
        rng = np.random.default_rng(seed)
        length = line_length()
        near_xy = [point_at(s, o) for s, o in zip(rng.uniform(20.0, length - 20.0, DENSE_NEAR),
                                                  rng.uniform(-0.9 * TOLERANCE, 0.9 * TOLERANCE, DENSE_NEAR))]
        xs_, ys_ = [p[0] for p in LINE], [p[1] for p in LINE]
        cx, cy = (min(xs_) + max(xs_)) / 2.0, (min(ys_) + max(ys_)) / 2.0
        hw = (max(xs_) - min(xs_)) / 2.0 * math.sqrt(20.0)
        hh = (max(ys_) - min(ys_)) / 2.0 * math.sqrt(20.0)
        rest = np.empty((0, 2))
        while len(rest) < n - DENSE_NEAR:
            xy = np.column_stack([rng.uniform(cx - hw, cx + hw, n), rng.uniform(cy - hh, cy + hh, n)])
            rest = np.vstack([rest, xy[_dist_to_line(xy[:, 0], xy[:, 1]) > 400.0]])
        xy = np.vstack([np.array(near_xy), rest[:n - DENSE_NEAR]])
        typ = rng.integers(0, len(DENSE_TYPES), n)
        null_type = rng.random(n) < 0.05
        depth = np.round(rng.uniform(5.0, 80.0, n), 1)
        null_elev = rng.random(n) < 0.10
        T = QMetaType.Type
        rows = []
        for k in range(n):
            x, y = float(xy[k, 0]), float(xy[k, 1])
            label = f"D-{k + 1:03d}" if k < DENSE_NEAR else f"X-{k + 1:05d}"
            rows.append((x, y, [label, None if null_type[k] else DENSE_TYPES[int(typ[k])], float(depth[k]),
                                None if null_elev[k] else round(plane_z(x, y), 2)]))
        mem = _memory_points(name, [("ExploName", T.QString), ("ExploType_resolved", T.QString),
                                    ("ExploDepth", T.Double), ("ExploElev", T.Double)], rows)
        # written under a name of its own, then renamed: a run starting at the same time never opens half a file
        tmp = os.path.join(cache, f"dense_{n}_{seed}_{key}.{os.getpid()}.tmp.gpkg")
        written = write_gpkg(mem, name, tmp)
        del written                         # (never iterated: OGR lets the file go)
        try:
            os.replace(tmp, path)
        except OSError:                     # another run made it first and holds it open
            if not os.path.isfile(path):
                raise
            try:
                os.remove(tmp)
            except OSError:
                pass
    lyr = QgsVectorLayer(f"{path}|layername={name}", name, "ogr")
    assert lyr.isValid() and lyr.featureCount() == n, path
    return lyr


def point_row(layer=None, **kw):
    """A cleaned exploration row (POINT_LAYER_DEFAULTS with `kw`; `layer` sets layer_id)."""
    from xsections.core.model import POINT_LAYER_DEFAULTS, clean_point_layer
    if layer is not None:
        kw["layer_id"] = layer.id()
    return clean_point_layer(dict(POINT_LAYER_DEFAULTS, **kw))


def seep_row(layer=None, **kw):
    """A cleaned other-points row (OTHER_POINT_DEFAULTS with `kw`; `layer` sets layer_id)."""
    from xsections.core.model import OTHER_POINT_DEFAULTS, clean_other_point
    if layer is not None:
        kw["layer_id"] = layer.id()
    return clean_other_point(dict(OTHER_POINT_DEFAULTS, **kw))


def explo_row(dock, i=0):
    """The dock's exploration row `i` (0.3.3: the per-layer widgets live in the rows, ui.point_rows.ExplorationRow)."""
    return dock.explo_rows[i]


def other_row(dock, i=0):
    """The dock's Other points row `i` (ui.point_rows.OtherPointsRow)."""
    return dock.other_rows[i]


# ---------------------------------------------------------------------------------------- 0.3.4: layer styles
# A memory layer's default renderer is a single symbol of a RANDOM colour: a layer drawn in Color gets one of these.
# Explorations' types as categories (value or None, label, colour): fixtures' ExploType values and a NULL one.
TYPE_CATS = [("Boring", "Boring", "#df9560"), ("Monitoring Well", "Monitoring Well", "#3fcaa2"),
             ("Test Pit", "Test Pit", "#80a7ea"), ("CPT", "CPT", "#cec063"), (None, "", "#e049db")]
# His Cumberland.qgz style of Explor_AESI_pt (categorized by "ExploType"), read from a byte copy of the project, in
# its order: each category value is the literal string (his ExploType values are these strings).
CUMBERLAND_AESI = [
    ("CPT, PT, DCP", "CPT, PT, DCP", "#d06c71"), ("EB, B, E, BH, GSHP, ST", "EB, B, E, BH, GSHP, ST", "#df9560"),
    ("EP, TP", "EP, TP", "#80a7ea"), ("GEOTECHNICAL", "GEOTECHNICAL", "#6fb9c8"), ("GP", "GP", "#79e494"),
    ("HB, HA, HH, HE", "HB, HA, HH, HE", "#cec063"), ("IT", "IT", "#7f74df"),
    ("MW, EB-1W, TW, OBW", "MW, EB-1W, TW, OBW", "#3fcaa2"), ("PIT DRAIN, PD, DT", "PIT DRAIN, PD, DT", "#e38ab6"),
    ("UIC WELL, DD", "UIC WELL, DD", "#6fdd54"), ("V, VB, VH", "V, VB, VH", "#8223cb"),
    ("WP, DP, P, PZ, PIEZ", "WP, DP, P, PZ, PIEZ", "#b3de5e"), (None, "", "#e049db")]


def _marker(color, outline="#232323"):
    from qgis.core import QgsMarkerSymbol
    return QgsMarkerSymbol.createSimple({"color": color, "outline_color": outline})


def categorized_renderer(field, cats):
    """A categorized renderer on `field`: cats [(value or None, label, "#rrggbb")], in that order, each a simple
    marker of that fill with a #232323 outline, all ticked."""
    from qgis.core import QgsCategorizedSymbolRenderer, QgsRendererCategory
    return QgsCategorizedSymbolRenderer(field, [QgsRendererCategory(v, _marker(c), label, True)
                                                for v, label, c in cats])


def single_renderer(color, outline="#232323"):
    """A single-symbol renderer: a simple marker of fill `color` and outline `outline`."""
    from qgis.core import QgsSingleSymbolRenderer
    return QgsSingleSymbolRenderer(_marker(color, outline))


def rule_renderer(rules):
    """A rule-based renderer: rules [(filter expression or "ELSE", label, "#rrggbb", active)] under a root rule, in
    that order, each with a simple marker of that fill."""
    from qgis.core import QgsRuleBasedRenderer
    root = QgsRuleBasedRenderer.Rule(None)
    for flt, label, color, active in rules:
        rule = QgsRuleBasedRenderer.Rule(_marker(color), 0, 0, flt, label)
        rule.setActive(bool(active))
        root.appendChild(rule)
    return QgsRuleBasedRenderer(root)


def color_model(model, row=0, cats=TYPE_CATS, kind="categorized"):
    """`model` (a hand-made SectionModel, changed in place and returned) with row `row` drawn in Color from a layer
    style of `cats` [(value or None, label, "#rrggbb")]: the row's PointLayerInfo (appended when the model has no such
    row, with any missing rows before it as Black rows) gets look "color", no colour of its own and that style; each
    hit of the row gets look "color" and the (index, colour) of the cat whose value is its type value (a None value
    matches a blank type value), else (-1, ""): drawn black, as a feature its style draws with no symbol."""
    from xsections.core.model import LayerStyle, PointLayerInfo, StyleItem
    from xsections.core.symbology import NO_VALUE_LABEL
    style = LayerStyle(kind=kind, field="ExploType",
                       items=[StyleItem(key=str(i), label=lab or NO_VALUE_LABEL, color=c)
                              for i, (_v, lab, c) in enumerate(cats)])
    while len(model.point_layers) <= row:
        j = len(model.point_layers)
        look = "color" if j == row else "black"
        model.point_layers.append(PointLayerInfo(
            index=j, layer_id=f"L{j}", name="Explorations" if j == row else f"Explorations {j + 1}",
            layer_name="Explorations" if j == row else f"Explorations {j + 1}", look=look, color="", in_range=True,
            on=True, row=point_row(layer_id=f"L{j}", look=look)))
    info = model.point_layers[row]
    info.look, info.color, info.style = "color", "", style
    for h in model.hits:
        if h.layer_index != row:
            continue
        h.layer_id, h.look = f"L{row}", "color"
        found = [(i, c) for i, (v, _lab, c) in enumerate(cats) if (v or "") == (h.type_value or "")]
        h.style_rank, h.color = found[0] if found else (-1, "")
    return model
