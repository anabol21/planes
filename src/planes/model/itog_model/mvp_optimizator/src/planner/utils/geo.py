"""Геометрические утилиты: проекции, преобразования."""

from __future__ import annotations

from pyproj import Transformer
from shapely.geometry import Polygon, shape
from shapely.ops import transform


def make_local_transformer(lon0: float, lat0: float):
    """WGS84 ↔ локальная ENU (метры), центр в (lon0, lat0)."""
    proj_str = (
        f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} "
        f"+x_0=0 +y_0=0 +units=m +datum=WGS84 +no_defs"
    )
    fwd = Transformer.from_crs("EPSG:4326", proj_str, always_xy=True)
    inv = Transformer.from_crs(proj_str, "EPSG:4326", always_xy=True)
    return fwd, inv


def geojson_to_local(polygon_geojson: dict, fwd) -> Polygon:
    """GeoJSON Polygon (lon, lat) → метры."""
    poly_wgs = shape(polygon_geojson)
    return transform(fwd.transform, poly_wgs)


def local_to_wgs(lon: float, lat: float, inv) -> tuple[float, float]:
    return inv.transform(lon, lat)